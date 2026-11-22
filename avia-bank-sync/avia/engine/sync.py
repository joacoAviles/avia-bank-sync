"""Motor de sincronización, independiente de cada banco."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .. import db
from ..connectors import get_connector_class
from ..connectors.base import (
    AuthorizationRequired,
    BankConnector,
    BankError,
    BankTransaction,
    Capability,
    ConnectorUnavailable,
)
from ..connectors.portal import ExtractionPending
from ..crypto import SecretBox
from . import repo, transfers

log = logging.getLogger("avia.engine")

VALID_STATUS = {"pending", "booked"}


class SyncInProgress(Exception):
    """Ya hay otra sincronización tomando el lock."""
    pass


def _validate(t: BankTransaction, currency: str) -> str | None:
    """Revisa que un movimiento sea válido; devuelve el motivo si no lo es."""
    if not t.external_id:
        return "sin identificador bancario"
    if t.status not in VALID_STATUS:
        return f"estado inválido {t.status!r}"
    if not isinstance(t.amount, Decimal):
        return "monto no es Decimal (riesgo de error de precisión)"
    if len(t.currency) != 3:
        return "moneda inválida"
    if t.status == "booked" and t.booked_date is None:
        return "contabilizado sin fecha contable"
    if t.original_currency and t.original_currency != t.currency and (t.fx_rate is None or t.fx_date is None):
        return "conversión cambiaria sin tipo de cambio/fecha registrados"
    return None


class SyncEngine:
    """Motor de sincronización: por cada conexión lee el banco y guarda sin duplicar."""
    def __init__(self, settings, box: SecretBox, today=None):
        """Recibe configuración, caja de cifrado y un reloj opcional (pruebas)."""
        self.settings = settings
        self.box = box
        self._today = today

    def today(self) -> date:
        """Fecha de hoy en la zona configurada (o la del reloj de pruebas)."""
        if self._today:
            return self._today()
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(self.settings.timezone)).date()

    # ------------------------------------------------------------------ API
    def run(self, trigger: str, connection_ids: list[str] | None = None) -> dict[str, Any]:
        """Ejecuta una sincronización completa bajo lock y devuelve estado y estadísticas."""
        with db.sync_lock() as got:
            if not got:
                raise SyncInProgress("Ya existe una sincronización en curso")
            run_id = uuid.uuid4()
            with db.tx() as conn:
                conn.execute("INSERT INTO sync_runs (id, trigger) VALUES (%s,%s)", (run_id, trigger))
            stats: dict[str, Any] = {"connections": 0, "accounts": 0, "new": 0, "updated": 0, "unchanged": 0,
                                     "pending_booked": 0, "reversed": 0, "rejected": 0, "review": 0,
                                     "transfers_paired": 0, "errors": []}
            try:
                for conn_row in self._connections(connection_ids):
                    stats["connections"] += 1
                    self._sync_connection(run_id, conn_row, stats)
                with db.tx() as conn:
                    stats["transfers_paired"] = transfers.pair_card_payments(conn, run_id)
                status = "succeeded" if not stats["errors"] else ("partial" if stats["accounts"] else "failed")
            except Exception as exc:  # error inesperado: se registra y se propaga
                log.exception("sincronización abortada")
                status = "failed"
                stats["errors"].append({"error": type(exc).__name__, "message": str(exc)[:300]})
            with db.tx() as conn:
                conn.execute(
                    "UPDATE sync_runs SET status = %s, finished_at = now(), stats = %s, error = %s WHERE id = %s",
                    (status, json.dumps(stats, default=str),
                     "; ".join(e.get("message", "") for e in stats["errors"])[:2000] or None, run_id),
                )
            log.info("sincronización terminada", extra={"run_id": str(run_id), "status": status, "stats": stats})
            return {"run_id": str(run_id), "status": status, "stats": stats}

    # ------------------------------------------------------------- internos
    def _connections(self, ids):
        """Conexiones activas a sincronizar (todas o las pedidas)."""
        with db.tx() as conn:
            q = ("SELECT c.*, b.connector, b.id AS bank_key FROM connections c JOIN banks b ON b.id = c.bank_id"
                 " WHERE c.deleted_at IS NULL AND c.status <> 'disconnected'")
            params: list[Any] = []
            if ids:
                q += " AND c.id = ANY(%s::uuid[])"
                params.append(ids)
            return conn.execute(q + " ORDER BY c.created_at", params).fetchall()

    def build_connector(self, conn_row) -> BankConnector:
        """Instancia el conector de una conexión con sus credenciales descifradas."""
        key = conn_row["connector"]
        if key not in self.settings.enabled_connectors:
            raise ConnectorUnavailable(conn_row["bank_id"], f"Conector '{key}' no habilitado en AVIA_ENABLED_CONNECTORS", "")
        with db.tx() as conn:
            cred = conn.execute("SELECT ciphertext FROM credentials WHERE connection_id = %s",
                                (conn_row["id"],)).fetchone()
        creds = self.box.decrypt(cred["ciphertext"]) if cred else {}
        return get_connector_class(key)(creds)

    def store_credentials(self, conn, connection_id, creds: dict[str, Any]) -> None:
        """Guarda (cifradas) las credenciales de una conexión."""
        conn.execute(
            """
            INSERT INTO credentials (connection_id, ciphertext, key_id) VALUES (%s,%s,%s)
            ON CONFLICT (connection_id) DO UPDATE SET ciphertext = EXCLUDED.ciphertext,
              key_id = EXCLUDED.key_id, rotated_at = now()
            """,
            (connection_id, self.box.encrypt(creds), self.box.active_key_id),
        )

    def _set_connection_status(self, connection_id, status, error=None, *, success=False):
        """Actualiza estado y último error; con éxito marca last_success_at."""
        with db.tx() as conn:
            conn.execute(
                "UPDATE connections SET status = %s, last_error = %s, updated_at = now()"
                + (", last_success_at = now()" if success else "") + " WHERE id = %s",
                (status, error, connection_id),
            )
            if status == "connected":
                conn.execute("UPDATE pending_authorizations SET resolved_at = now()"
                             " WHERE connection_id = %s AND resolved_at IS NULL", (connection_id,))

    def _sync_connection(self, run_id, conn_row, stats) -> None:
        """Sincroniza una conexión: autentica, lee cuentas y saldos y sincroniza cada cuenta."""
        cid = conn_row["id"]
        try:
            connector = self.build_connector(conn_row)
            new_creds = connector.authenticate()
            if new_creds != connector.credentials:
                with db.tx() as conn:
                    self.store_credentials(conn, cid, new_creds)
            accounts = connector.get_accounts()
            balances = {b.external_account_id: b for b in connector.get_balances(accounts)}
        except AuthorizationRequired as exc:
            self._auth_required(run_id, cid, str(exc), stats)
            return
        except ExtractionPending as exc:
            # Login listo, extracción aún no implementada: no es un error de la conexión
            with db.tx() as conn:
                repo.event(conn, "info", "extraction_pending", str(exc), run_id=run_id, connection_id=cid)
            stats.setdefault("pending_extraction", []).append(str(cid))
            return
        except ConnectorUnavailable as exc:
            self._connection_error(run_id, cid, "connector_unavailable", exc.reason, stats)
            return
        except BankError as exc:
            self._connection_error(run_id, cid, "bank_error", str(exc), stats)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("error de conector")
            self._connection_error(run_id, cid, "connector_crash", f"{type(exc).__name__}: {exc}"[:300], stats)
            return

        failed = False
        for acct in accounts:
            try:
                self._sync_account(run_id, conn_row, connector, acct, balances.get(acct.external_id), stats)
                stats["accounts"] += 1
            except AuthorizationRequired as exc:
                self._auth_required(run_id, cid, str(exc), stats)
                return
            except Exception as exc:  # noqa: BLE001 — una cuenta no debe botar las demás
                failed = True
                log.exception("error sincronizando cuenta", extra={"account": acct.masked_number})
                stats["errors"].append({"connection": str(cid), "account": acct.masked_number,
                                        "message": f"{type(exc).__name__}: {exc}"[:300]})
                with db.tx() as conn:
                    repo.event(conn, "error", "account_failed", f"Falló la cuenta {acct.masked_number}",
                               run_id=run_id, connection_id=cid, data={"error": str(exc)[:300]})
        if failed:
            self._set_connection_status(cid, "error", "Una o más cuentas fallaron; ver eventos")
        else:
            self._set_connection_status(cid, "connected", None, success=True)

    def _auth_required(self, run_id, cid, reason, stats):
        """Marca la conexión como «requiere reautorización» y lo deja pendiente."""
        with db.tx() as conn:
            conn.execute("UPDATE connections SET status = 'authorization_required', last_error = %s,"
                         " updated_at = now() WHERE id = %s", (reason, cid))
            conn.execute("INSERT INTO pending_authorizations (id, connection_id, reason) VALUES (%s,%s,%s)"
                         " ON CONFLICT DO NOTHING", (uuid.uuid4(), cid, reason))
            repo.event(conn, "warning", "authorization_required", reason, run_id=run_id, connection_id=cid)
        stats["errors"].append({"connection": str(cid), "message": f"Requiere reautorización: {reason}"})

    def _connection_error(self, run_id, cid, kind, reason, stats):
        """Marca la conexión con error y lo registra."""
        self._set_connection_status(cid, "error", reason)
        with db.tx() as conn:
            repo.event(conn, "error", kind, reason, run_id=run_id, connection_id=cid)
        stats["errors"].append({"connection": str(cid), "message": reason})

    def _sync_account(self, run_id, conn_row, connector, acct, balance, stats) -> None:
        """Sincroniza una cuenta de forma atómica: movimientos, reversas, cursor y saldo."""
        today = self.today()
        with db.tx() as conn:  # todo el trabajo de una cuenta es atómico: movimientos + cursor + saldo
            ba_id = repo.upsert_bank_account(conn, conn_row["id"], acct)
            cursor = repo.get_cursor(conn, ba_id)
            if cursor:
                since = cursor - timedelta(days=self.settings.overlap_days)
            else:
                since = today - timedelta(days=min(self.settings.initial_history_days, self.settings.max_history_days))
            fetched = connector.get_transactions(acct, since)
            seen: set[str] = set()
            max_booked = cursor
            for t in fetched:
                problem = _validate(t, acct.currency)
                if problem:
                    stats["rejected"] += 1
                    repo.event(conn, "warning", "transaction_rejected", f"Movimiento rechazado: {problem}",
                               run_id=run_id, bank_account_id=ba_id, data={"external_id": t.external_id})
                    continue
                seen.add(t.external_id)
                if t.status == "booked" and (max_booked is None or t.booked_date > max_booked):
                    max_booked = t.booked_date
                existing = repo.find_by_identifier(conn, ba_id, "bank_id", t.external_id)
                if existing:
                    changed = repo.apply_update(conn, existing, t, run_id)
                    if changed:
                        stats["updated"] += 1
                        repo.event(conn, "info", "transaction_updated", "Movimiento modificado por el banco",
                                   run_id=run_id, bank_account_id=ba_id,
                                   data={"lineage_id": existing["lineage_id"], "fields": changed})
                    else:
                        stats["unchanged"] += 1
                    continue
                if t.status == "booked":
                    pend = None
                    ambiguous = False
                    if t.pending_ref:
                        cand = repo.find_by_identifier(conn, ba_id, "bank_id", t.pending_ref)
                        if cand and cand["status"] == "pending":
                            pend = cand
                    if pend is None:
                        pend, ambiguous = repo.conservative_pending_match(conn, ba_id, t)
                    if pend is not None:
                        repo.promote_pending(conn, pend, t, run_id)
                        stats["pending_booked"] += 1
                        continue
                    lineage = repo.lineage_id(conn_row["bank_key"], acct.external_id, t.external_id)
                    repo.insert_transaction(conn, bank_account_id=ba_id, lineage=lineage, t=t, run_id=run_id,
                                            needs_review=ambiguous,
                                            review_reason="Coincide con varios pendientes" if ambiguous else None)
                    if ambiguous:
                        stats["review"] += 1
                        repo.event(conn, "warning", "ambiguous_pending_match",
                                   "Contabilizado coincide con más de un pendiente; revisar en Actual",
                                   run_id=run_id, bank_account_id=ba_id, data={"lineage_id": lineage})
                    stats["new"] += 1
                else:
                    lineage = repo.lineage_id(conn_row["bank_key"], acct.external_id, t.external_id)
                    repo.insert_transaction(conn, bank_account_id=ba_id, lineage=lineage, t=t, run_id=run_id)
                    stats["new"] += 1

            if Capability.COMPLETE_PENDING_LIST in connector.capabilities:
                for row in repo.stale_pendings(conn, ba_id, since, seen):
                    conn.execute("UPDATE transactions SET status = 'reversed', needs_review = true,"
                                 " review_reason = %s, last_run_id = %s, updated_at = now() WHERE id = %s",
                                 ("El banco anuló el pendiente; si ya está en Actual como no conciliado, eliminarlo",
                                  run_id, row["id"]))
                    stats["reversed"] += 1
                    repo.event(conn, "warning", "pending_reversed", "Pendiente revertido por el banco",
                               run_id=run_id, bank_account_id=ba_id, data={"lineage_id": row["lineage_id"]})

            if balance is not None:
                repo.upsert_balance(conn, ba_id, balance.as_of or today, balance.booked, balance.available,
                                    balance.currency)
            repo.set_cursor(conn, ba_id, max_booked, run_id)


def recover_interrupted_runs() -> int:
    """Al arrancar: runs en 'running' sin lock vivo quedaron interrumpidos.

    Los cursores solo avanzan con commits confirmados, así que la próxima
    ejecución reanuda desde el último punto seguro sin reimportar nada.
    """
    if db.sync_lock_held():
        return 0
    with db.tx() as conn:
        rows = conn.execute(
            "UPDATE sync_runs SET status = 'interrupted', finished_at = now(),"
            " error = 'Proceso reiniciado durante la ejecución' WHERE status = 'running' RETURNING id"
        ).fetchall()
        for r in rows:
            repo.event(conn, "warning", "run_interrupted", "Ejecución interrumpida por reinicio; se reanudará",
                       run_id=r["id"])
    return len(rows)
