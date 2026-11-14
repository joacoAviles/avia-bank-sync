"""Casos de uso consumidos por la API (y por pruebas)."""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from . import db
from .connectors import REGISTRY, get_connector_class
from .connectors.base import AuthorizationRequired, BankError, ConnectorUnavailable
from .engine import actual_format, repo
from .engine.sync import SyncEngine, SyncInProgress
from .portal import rut as rutlib
from .portal.manager import LoginManager


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class AviaService:
    def __init__(self, settings, engine: SyncEngine):
        self.settings = settings
        self.engine = engine
        self._bg: threading.Thread | None = None
        self.next_run_provider = lambda: None
        self.logins = LoginManager()

    # ------------------------------------------------------------ estado
    def institutions(self) -> list[dict[str, Any]]:
        with db.tx() as conn:
            banks = conn.execute("SELECT * FROM banks ORDER BY CASE id WHEN 'banco-chile' THEN 1"
                                 " WHEN 'itau' THEN 2 WHEN 'ripley' THEN 3 ELSE 9 END, name").fetchall()
        out = []
        for b in banks:
            cls = REGISTRY.get(b["connector"])
            avail = cls.availability() if cls else {"available": False, "reason": "Sin conector", "doc": None}
            enabled = b["connector"] in self.settings.enabled_connectors
            out.append({
                "id": b["id"], "name": b["name"],
                "available": bool(avail["available"] and enabled),
                "reason": avail["reason"] if not avail["available"] else
                          (None if enabled else "Conector deshabilitado en AVIA_ENABLED_CONNECTORS"),
                "doc": avail["doc"],
                "setupFields": list(cls.setup_fields) if cls else [],
                "authMethod": getattr(cls, "auth_method", "none") if cls else "none",
                "testData": b["id"] == "sandbox",
            })
        return out

    def status(self) -> dict[str, Any]:
        with db.tx() as conn:
            conns = conn.execute(
                "SELECT c.id, c.label, c.status, c.last_error, c.last_success_at, b.name AS bank, c.bank_id,"
                " (SELECT count(*) FROM bank_accounts a WHERE a.connection_id = c.id AND a.active) AS accounts"
                " FROM connections c JOIN banks b ON b.id = c.bank_id WHERE c.deleted_at IS NULL"
                " ORDER BY c.created_at").fetchall()
            last_ok = conn.execute("SELECT max(finished_at) AS t FROM sync_runs WHERE status IN ('succeeded','partial')"
                                   ).fetchone()["t"]
            last_run = conn.execute("SELECT id, trigger, status, started_at, finished_at, stats FROM sync_runs"
                                    " ORDER BY started_at DESC LIMIT 1").fetchone()
            linked = conn.execute("SELECT count(*) AS n FROM account_mappings").fetchone()["n"]
            review = conn.execute("SELECT count(*) AS n FROM transactions WHERE needs_review").fetchone()["n"]
            imported = conn.execute("SELECT count(*) AS n FROM transactions WHERE status IN ('pending','booked')"
                                    ).fetchone()["n"]
        active = [c for c in conns if c["status"] != "disconnected"]
        if db.sync_lock_held():
            state = "syncing"
        elif not active:
            state = "not_configured"
        elif any(c["status"] == "authorization_required" for c in active):
            state = "authorization_required"
        elif any(c["status"] == "error" for c in active):
            state = "error"
        elif last_ok:
            state = "synchronized"
        else:
            state = "connected"
        return {
            "configured": bool(active),
            "state": state,
            "connections": [{**c, "id": str(c["id"])} for c in conns],
            "lastSuccessfulSync": last_ok,
            "lastRun": {**last_run, "id": str(last_run["id"])} if last_run else None,
            "nextScheduledSync": self.next_run_provider(),
            "isStale": self.is_stale(last_ok),
            "linkedAccounts": linked,
            "importedTransactions": imported,
            "needsReview": review,
        }

    def is_stale(self, last_ok: datetime | None) -> bool:
        if last_ok is None:
            return True
        return datetime.now(last_ok.tzinfo) - last_ok > timedelta(hours=self.settings.freshness_hours)

    # ------------------------------------------------------- conexiones
    def create_connection(self, institution: str, label: str | None, params: dict[str, Any]) -> dict:
        with db.tx() as conn:
            bank = conn.execute("SELECT * FROM banks WHERE id = %s", (institution,)).fetchone()
        if not bank:
            raise ServiceError(404, "UNKNOWN_INSTITUTION", "Institución desconocida")
        cls = get_connector_class(bank["connector"])
        avail = cls.availability()
        if not avail["available"]:
            raise ServiceError(409, "INSTITUTION_BLOCKED", avail["reason"])
        if bank["connector"] not in self.settings.enabled_connectors:
            raise ServiceError(409, "CONNECTOR_DISABLED", "Conector deshabilitado en AVIA_ENABLED_CONNECTORS")
        if getattr(cls, "auth_method", "none") == "portal_login":
            raise ServiceError(409, "USE_LOGIN_FLOW", "Este banco se conecta iniciando sesión (/v1/logins)")
        # Solo se aceptan los campos declarados por el conector (nunca guardar extras)
        allowed = {f["name"] for f in cls.setup_fields}
        creds = {k: v for k, v in (params or {}).items() if k in allowed and k != "label"}
        connector = cls(creds)
        try:
            creds = connector.authenticate()
            accounts = connector.get_accounts()
        except AuthorizationRequired as exc:
            raise ServiceError(401, "AUTHORIZATION_FAILED", str(exc)) from exc
        except (BankError, ConnectorUnavailable) as exc:
            raise ServiceError(502, "BANK_ERROR", str(exc)) from exc
        cid = uuid.uuid4()
        with db.tx() as conn:
            conn.execute("INSERT INTO connections (id, bank_id, label) VALUES (%s,%s,%s)",
                         (cid, institution, label or bank["name"]))
            self.engine.store_credentials(conn, cid, creds)
            for a in accounts:
                repo.upsert_bank_account(conn, cid, a)
            repo.event(conn, "info", "connection_created", f"Conexión creada con {bank['name']}", connection_id=cid)
        self.start_background_sync("manual", [str(cid)])
        return {"id": str(cid), "accounts": len(accounts)}

    def delete_connection(self, cid: str) -> None:
        with db.tx() as conn:
            r = conn.execute("UPDATE connections SET status = 'disconnected', deleted_at = now(), updated_at = now()"
                             " WHERE id = %s AND deleted_at IS NULL RETURNING id", (cid,)).fetchone()
            if not r:
                raise ServiceError(404, "NOT_FOUND", "Conexión no encontrada")
            conn.execute("DELETE FROM credentials WHERE connection_id = %s", (cid,))  # se borra el secreto
            conn.execute("UPDATE bank_accounts SET active = false WHERE connection_id = %s", (cid,))
            repo.event(conn, "info", "connection_deleted", "Conexión desconectada; historial conservado",
                       connection_id=cid)

    def reauthorize(self, cid: str, params: dict[str, Any]) -> dict:
        with db.tx() as conn:
            row = conn.execute("SELECT c.*, b.connector, b.id AS bank_key FROM connections c JOIN banks b"
                               " ON b.id = c.bank_id WHERE c.id = %s AND c.deleted_at IS NULL", (cid,)).fetchone()
        if not row:
            raise ServiceError(404, "NOT_FOUND", "Conexión no encontrada")
        try:
            connector = self.engine.build_connector(row)
            connector.credentials.update({k: v for k, v in (params or {}).items()
                                          if k in {f["name"] for f in connector.setup_fields}})
            creds = connector.refresh_authorization()
            connector.credentials = creds
            creds = connector.authenticate()
        except AuthorizationRequired as exc:
            raise ServiceError(401, "AUTHORIZATION_FAILED", str(exc)) from exc
        except (BankError, ConnectorUnavailable) as exc:
            raise ServiceError(502, "BANK_ERROR", str(exc)) from exc
        with db.tx() as conn:
            self.engine.store_credentials(conn, cid, creds)
            conn.execute("UPDATE connections SET status = 'connected', last_error = NULL, updated_at = now()"
                         " WHERE id = %s", (cid,))
            conn.execute("UPDATE pending_authorizations SET resolved_at = now() WHERE connection_id = %s"
                         " AND resolved_at IS NULL", (cid,))
            repo.event(conn, "info", "reauthorized", "Conexión reautorizada", connection_id=cid)
        self.start_background_sync("manual", [cid])
        return {"id": cid, "status": "connected"}

    # ------------------------------------------------------- login portal
    def login_start(self, institution: str, rut: str, password: str, label: str | None,
                    connection_id: str | None = None) -> dict[str, Any]:
        with db.tx() as conn:
            bank = conn.execute("SELECT * FROM banks WHERE id = %s", (institution,)).fetchone()
        if not bank:
            raise ServiceError(404, "UNKNOWN_INSTITUTION", "Institución desconocida")
        cls = get_connector_class(bank["connector"])
        if getattr(cls, "auth_method", "none") != "portal_login":
            raise ServiceError(409, "NOT_A_PORTAL", "Esta institución no usa inicio de sesión")
        if bank["connector"] not in self.settings.enabled_connectors:
            raise ServiceError(409, "CONNECTOR_DISABLED", "Conector deshabilitado en AVIA_ENABLED_CONNECTORS")
        if connection_id:
            with db.tx() as conn:
                row = conn.execute("SELECT * FROM connections WHERE id = %s AND bank_id = %s AND deleted_at IS NULL",
                                   (connection_id, institution)).fetchone()
            if not row:
                raise ServiceError(404, "NOT_FOUND", "Conexión no encontrada")
            if not password:  # reingreso con la clave guardada
                creds = self.engine.build_connector({**row, "connector": bank["connector"]}).credentials
                rut, password = creds.get("rut", rut), creds.get("password", "")
        if not rutlib.is_valid(rut):
            raise ServiceError(422, "INVALID_RUT", "El RUT no es válido")
        if not password or len(password) > 64:
            raise ServiceError(422, "INVALID_PASSWORD", "Ingresa tu clave")

        def on_success(sess, result):
            return self._store_portal_login(institution, bank["name"], label, connection_id,
                                            rut, sess_password, result)

        sess_password = password
        try:
            sess = self.logins.start(institution, rut, password, on_success)
        except RuntimeError as exc:
            raise ServiceError(429, "TOO_MANY_LOGINS", str(exc)) from exc
        return sess.snapshot(include_screenshot=False)

    def _store_portal_login(self, institution, bank_name, label, connection_id, rut, password, result):
        from datetime import datetime, timezone
        creds = {"rut": rutlib.clean(rut), "password": password, "storage_state": result.storage_state,
                 "session_at": datetime.now(timezone.utc).isoformat()}
        with db.tx() as conn:
            if connection_id:
                cid = connection_id
                conn.execute("UPDATE connections SET status = 'connected', last_error = NULL, updated_at = now()"
                             " WHERE id = %s", (cid,))
                conn.execute("UPDATE pending_authorizations SET resolved_at = now() WHERE connection_id = %s"
                             " AND resolved_at IS NULL", (cid,))
                repo.event(conn, "info", "portal_login", f"Sesión renovada en {bank_name}", connection_id=cid)
            else:
                cid = str(uuid.uuid4())
                conn.execute("INSERT INTO connections (id, bank_id, label) VALUES (%s,%s,%s)",
                             (cid, institution, label or f"{bank_name} · {rutlib.mask(rut)}"))
                repo.event(conn, "info", "portal_login", f"Conexión creada con {bank_name}", connection_id=cid)
            self.engine.store_credentials(conn, cid, creds)
        return {"connectionId": cid}

    def login_status(self, sid: str, include_screenshot: bool = True) -> dict[str, Any]:
        sess = self.logins.get(sid)
        if not sess:
            raise ServiceError(404, "LOGIN_NOT_FOUND", "La sesión de ingreso no existe o expiró")
        return sess.snapshot(include_screenshot)

    def login_input(self, sid: str, cmd: dict[str, Any]) -> dict[str, Any]:
        sess = self.logins.get(sid)
        if not sess:
            raise ServiceError(404, "LOGIN_NOT_FOUND", "La sesión de ingreso no existe o expiró")
        if cmd.get("type") not in {"click", "type", "key", "scroll", "cancel"}:
            raise ServiceError(422, "INVALID_INPUT", "Acción no permitida")
        sess.send(cmd)
        return {"ok": True}

    # ------------------------------------------------------------ cuentas
    def accounts(self) -> list[dict[str, Any]]:
        with db.tx() as conn:
            rows = conn.execute(
                """
                SELECT a.*, b.name AS institution, b.id AS bank_key, c.status AS connection_status,
                       s.booked, s.available, m.actual_account_id
                FROM bank_accounts a JOIN connections c ON c.id = a.connection_id JOIN banks b ON b.id = c.bank_id
                LEFT JOIN LATERAL (SELECT booked, available FROM balance_snapshots WHERE bank_account_id = a.id
                                   ORDER BY snapshot_date DESC LIMIT 1) s ON true
                LEFT JOIN account_mappings m ON m.bank_account_id = a.id
                WHERE a.active AND c.deleted_at IS NULL ORDER BY b.name, a.name
                """).fetchall()
        return [{
            "account_id": str(r["id"]),
            "name": f"{r['name']} {r['masked_number'] or ''}".strip(),
            "institution": r["institution"],
            "institutionId": r["bank_key"],
            "type": r["account_type"],
            "currency": r["currency"],
            "mask": r["masked_number"],
            "balance": actual_format.to_actual_integer(r["booked"]) if r["booked"] is not None else 0,
            "availableBalance": actual_format.to_actual_integer(r["available"]) if r["available"] is not None else None,
            "linkedActualAccountId": r["actual_account_id"],
            "connectionStatus": r["connection_status"],
        } for r in rows]

    def link(self, bank_account_id: str, actual_account_id: str) -> None:
        with db.tx() as conn:
            self._ensure_mapping(conn, bank_account_id, actual_account_id)

    def unlink_actual(self, actual_account_id: str) -> int:
        with db.tx() as conn:
            n = conn.execute("DELETE FROM account_mappings WHERE actual_account_id = %s",
                             (actual_account_id,)).rowcount
            repo.event(conn, "info", "account_unlinked", "Cuenta desvinculada en Actual",
                       data={"actual_account_id": actual_account_id})
        return n

    @staticmethod
    def _ensure_mapping(conn, bank_account_id, actual_account_id):
        conn.execute("INSERT INTO actual_accounts (id) VALUES (%s) ON CONFLICT (id) DO UPDATE"
                     " SET last_seen_at = now()", (actual_account_id,))
        prev = conn.execute("SELECT actual_account_id FROM account_mappings WHERE bank_account_id = %s",
                            (bank_account_id,)).fetchone()
        if prev and prev["actual_account_id"] == actual_account_id:
            return
        conn.execute(
            "INSERT INTO account_mappings (bank_account_id, actual_account_id) VALUES (%s,%s)"
            " ON CONFLICT (bank_account_id) DO UPDATE SET actual_account_id = EXCLUDED.actual_account_id,"
            " updated_at = now()", (bank_account_id, actual_account_id))
        repo.event(conn, "info", "account_linked", "Cuenta vinculada con Actual", bank_account_id=bank_account_id,
                   data={"actual_account_id": actual_account_id,
                         "previous": prev["actual_account_id"] if prev else None})

    # ------------------------------------------------------- movimientos
    def transactions_for_actual(self, bank_account_id: str, start_date: date,
                                actual_account_id: str | None) -> dict[str, Any]:
        try:
            uuid.UUID(bank_account_id)
        except ValueError as exc:
            raise ServiceError(404, "ACCOUNT_NOT_FOUND", "Cuenta no encontrada") from exc
        with db.tx() as conn:
            acct = conn.execute(
                "SELECT a.*, c.id AS cid, c.status AS cstatus, c.last_error, c.last_success_at, c.deleted_at"
                " FROM bank_accounts a JOIN connections c ON c.id = a.connection_id WHERE a.id = %s",
                (bank_account_id,)).fetchone()
        if not acct or acct["deleted_at"] is not None:
            raise ServiceError(404, "ACCOUNT_NOT_FOUND", "La cuenta ya no existe en AVIA (conexión eliminada)")

        # Al consultar desde Actual: si los datos están viejos y no hay otra ejecución, sincronizar esa conexión.
        if self.is_stale(acct["last_success_at"]) and acct["cstatus"] != "authorization_required":
            try:
                self.engine.run("actual_pull", [str(acct["cid"])])
            except SyncInProgress:
                pass
            with db.tx() as conn:
                acct = {**acct, **conn.execute("SELECT status AS cstatus, last_error FROM connections WHERE id = %s",
                                               (acct["cid"],)).fetchone()}
        if acct["cstatus"] == "authorization_required":
            raise ServiceError(200, "ITEM_LOGIN_REQUIRED", acct["last_error"] or "Se requiere reautorización")

        start_date = max(start_date, date.today() - timedelta(days=self.settings.max_history_days))
        with db.tx() as conn:
            if actual_account_id:
                self._ensure_mapping(conn, bank_account_id, actual_account_id)
            txns = conn.execute(
                "SELECT * FROM transactions WHERE bank_account_id = %s AND status IN ('pending','booked')"
                " AND value_date >= %s ORDER BY COALESCE(booked_date, value_date) DESC, value_date DESC,"
                " created_at DESC", (bank_account_id, start_date)).fetchall()
            peers = conn.execute(
                """
                SELECT t.id, m.actual_account_id, p.lineage_id AS peer_lineage FROM transactions t
                JOIN transactions p ON p.id = t.transfer_peer_id
                JOIN account_mappings m ON m.bank_account_id = p.bank_account_id
                WHERE t.bank_account_id = %s AND t.kind = 'card_payment' AND t.amount < 0
                """, (bank_account_id,)).fetchall()
            bal = conn.execute("SELECT * FROM balance_snapshots WHERE bank_account_id = %s"
                               " ORDER BY snapshot_date DESC LIMIT 1", (bank_account_id,)).fetchone()
        transfer_map = {p["id"]: (p["actual_account_id"], p["peer_lineage"]) for p in peers}
        return actual_format.build_response(txns, transfer_map, bal, acct["currency"])

    # ---------------------------------------------------- conciliación
    def record_actual_balance(self, bank_account_id: str, cleared_balance_integer: int) -> dict[str, Any]:
        actual = Decimal(cleared_balance_integer) / 100
        with db.tx() as conn:
            snap = conn.execute("SELECT * FROM balance_snapshots WHERE bank_account_id = %s"
                                " ORDER BY snapshot_date DESC LIMIT 1", (bank_account_id,)).fetchone()
            if not snap or snap["booked"] is None:
                raise ServiceError(404, "NO_BALANCE", "Sin saldo bancario registrado para esta cuenta")
            diff = snap["booked"] - actual
            conn.execute("UPDATE balance_snapshots SET actual_calculated = %s, difference = %s WHERE id = %s",
                         (actual, diff, snap["id"]))
            pending = conn.execute("SELECT count(*) AS n, COALESCE(sum(amount),0) AS s FROM transactions"
                                   " WHERE bank_account_id = %s AND status = 'pending'",
                                   (bank_account_id,)).fetchone()
            reversed_ = conn.execute("SELECT count(*) AS n FROM transactions WHERE bank_account_id = %s"
                                     " AND status = 'reversed' AND needs_review", (bank_account_id,)).fetchone()
            causes = []
            if diff != 0:
                if reversed_["n"]:
                    causes.append(f"{reversed_['n']} pendiente(s) revertido(s) que pueden seguir en Actual")
                causes.append("movimientos editados o creados manualmente en Actual")
                causes.append("saldo inicial de la cuenta distinto al del banco")
                repo.event(conn, "warning", "balance_mismatch",
                           f"Diferencia de saldo {diff} {snap['currency']} al {snap['snapshot_date']}",
                           bank_account_id=bank_account_id,
                           data={"bank_booked": snap["booked"], "actual_cleared": actual, "causes": causes})
        return {"date": snap["snapshot_date"], "bankBooked": snap["booked"], "bankAvailable": snap["available"],
                "actualCleared": actual, "difference": diff, "possibleCauses": causes,
                "pendingCount": pending["n"], "pendingAmount": pending["s"]}

    def reconciliation(self) -> list[dict[str, Any]]:
        with db.tx() as conn:
            return conn.execute(
                """
                SELECT DISTINCT ON (a.id) a.id AS bank_account_id, a.name, a.masked_number, m.actual_account_id,
                       s.snapshot_date, s.booked, s.available, s.actual_calculated, s.difference, s.currency
                FROM bank_accounts a JOIN balance_snapshots s ON s.bank_account_id = a.id
                LEFT JOIN account_mappings m ON m.bank_account_id = a.id
                WHERE a.active ORDER BY a.id, s.snapshot_date DESC
                """).fetchall()

    # ------------------------------------------------------ ejecuciones
    def start_background_sync(self, trigger: str, connection_ids: list[str] | None = None,
                              on_done=None) -> bool:
        if db.sync_lock_held() or (self._bg and self._bg.is_alive()):
            return False

        def work():
            try:
                res = self.engine.run(trigger, connection_ids)
                if on_done:
                    on_done(res)
            except SyncInProgress:
                pass

        self._bg = threading.Thread(target=work, name=f"sync-{trigger}", daemon=True)
        self._bg.start()
        return True

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with db.tx() as conn:
            return conn.execute("SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT %s", (limit,)).fetchall()

    def events(self, limit: int = 100, level: str | None = None) -> list[dict[str, Any]]:
        with db.tx() as conn:
            if level:
                return conn.execute("SELECT * FROM sync_events WHERE level = %s ORDER BY id DESC LIMIT %s",
                                    (level, limit)).fetchall()
            return conn.execute("SELECT * FROM sync_events ORDER BY id DESC LIMIT %s", (limit,)).fetchall()

    def review_items(self) -> list[dict[str, Any]]:
        with db.tx() as conn:
            return conn.execute(
                "SELECT t.lineage_id, t.status, t.value_date, t.amount, t.currency, t.description, t.review_reason,"
                " a.name AS account FROM transactions t JOIN bank_accounts a ON a.id = t.bank_account_id"
                " WHERE t.needs_review ORDER BY t.value_date DESC LIMIT 200").fetchall()


def santiago_now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))
