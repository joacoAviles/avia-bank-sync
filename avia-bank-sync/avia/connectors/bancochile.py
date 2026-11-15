"""Banco de Chile (Mi Banco Chile personas): lectura de cuentas, saldos y movimientos.

Usa los mismos endpoints JSON que consume el propio portal con tu sesión. Endpoints
(observados en el reconocimiento del portal, ver tools/grabador.mjs):
  - selectorproductos/obtenerProductos?incluirTarjetas  → cuentas y tarjetas
  - bff-pper-prd-cta-movimientos/movimientos/getCartola → movimientos de la cuenta corriente
  - tarjeta-credito-digital/saldo/obtener-saldo          → cupo de la tarjeta
  - tarjeta-credito-digital/movimientos-no-facturados    → compras del período abierto
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from ..portal.banks import PORTALS
from ..portal.client import PortalClient
from .base import AuthorizationRequired, Balance, BankAccount, BankError, BankTransaction, Capability
from .portal import PortalConnector

BASE = "https://portalpersonas.bancochile.cl/mibancochile/rest/persona/"
MORE = {"S", "s", "1", "true", "True", "SI", "Si"}


def clp(v: Any) -> Decimal:
    """'12.345' | '-12.345' | 12345 | 12345.0 → Decimal (CLP no usa decimales)."""
    if v is None or v == "":
        return Decimal(0)
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip()
    neg = s.startswith("-") or s.endswith("-")
    s = re.sub(r"[^\d,]", "", s)
    if "," in s:
        s = s.replace(",", ".")
    d = Decimal(s or "0")
    return -d if neg else d


def to_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and v > 10**9:
        ts = v / 1000 if v > 10**11 else v
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().date()
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"(\d{2})[-/](\d{2})[-/](\d{4})", s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    return None


def _h(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


class BancoChilePortal(PortalConnector):
    bank_id = portal_id = "banco-chile"
    display_name = "Banco de Chile"
    capabilities = frozenset({Capability.ACCOUNTS, Capability.BALANCES, Capability.AVAILABLE_BALANCE,
                              Capability.TRANSACTIONS, Capability.CREDIT_CARDS, Capability.INSTALLMENTS})

    def __init__(self, credentials=None):
        super().__init__(credentials)
        self._data: dict[str, dict[str, Any]] | None = None
        self.diagnostics: list = []

    # ------------------------------------------------------------ sesión
    def authenticate(self) -> dict[str, Any]:
        return self.credentials  # la sesión se valida al abrir el portal en get_accounts

    # ------------------------------------------------------------ extracción
    def _load(self, since: date | None = None) -> dict[str, dict[str, Any]]:
        if self._data is not None:
            return self._data
        since = since or (date.today() - timedelta(days=90))
        data: dict[str, dict[str, Any]] = {}
        portal = PORTALS[self.portal_id]
        with PortalClient(portal, self.credentials, "/mibancochile/rest/") as c:
            self.diagnostics = c.log  # referencia viva: sirve aunque algo falle más abajo
            prods = c.call("GET", BASE + "selectorproductos/selectorProductos/obtenerProductos?incluirTarjetas=true")
            rut, nombre = (prods or {}).get("rut"), (prods or {}).get("nombre")
            for p in (prods or {}).get("productos", []):
                num = str(p.get("numero") or "").strip()
                if not num or not (p.get("tipo") or "").lower().startswith("cuenta"):
                    continue  # líneas de crédito y seguros: la línea viene dentro de la cartola
                vista = (p.get("claseCuenta") or "").upper().startswith("VTA")
                acct = BankAccount(num, p.get("label") or "Cuenta", "vista" if vista else "checking",
                                   p.get("codigoMoneda") or "CLP", p.get("mascara") or num[-4:])
                data[num] = {"acct": acct, "p": p, "txs": [], "bal": None}
                try:
                    self._checking(c, data[num], rut, nombre, since)
                except BankError as exc:
                    data[num]["error"] = str(exc)
            try:
                self._infotarj = c.call("POST", BASE + "tarjetas/widget/informacion-tarjetas", {}) or []
            except BankError:
                self._infotarj = []
            for it in self._infotarj:
                cid = str(it.get("idProducto") or "").strip()
                if not cid:
                    continue
                last4 = re.sub(r"\D", "", str(it.get("numero") or ""))[-4:]
                acct = BankAccount(cid, f"{it.get('marca') or 'Tarjeta'} {it.get('tipo') or ''}".strip(),
                                   "credit_card", "CLP", f"****{last4}" if last4 else None)
                data[cid] = {"acct": acct, "p": it, "txs": [], "bal": None}
                try:
                    self._card(c, data[cid], nombre, since)
                except BankError as exc:
                    data[cid]["error"] = str(exc)
            self.diagnostics = c.log
        self._data = data
        return data

    @staticmethod
    def _account_body(p, rut, nombre):
        return {"nombreCliente": nombre, "rutCliente": rut, "numero": p.get("numero"), "mascara": p.get("mascara"),
                "selected": True, "codigoProducto": p.get("codigo") or "CTD", "claseCuenta": p.get("claseCuenta"),
                "moneda": p.get("codigoMoneda") or "CLP"}

    def _checking(self, c: PortalClient, rec, rut, nombre, since: date) -> None:
        p, cur = rec["p"], rec["acct"].currency
        body_acct = self._account_body(p, rut, nombre)
        desde, seen = 0, set()
        dbg = rec.setdefault("debug", {"pages": 0, "raw": 0, "no_date": 0, "old": 0})
        for _ in range(30):
            r = c.call("POST", BASE + "bff-pper-prd-cta-movimientos/movimientos/getCartola",
                       {"cuentaSeleccionada": body_acct,
                        "cabecera": {"statusGenerico": True, "paginacionDesde": desde}})
            if rec["bal"] is None and r:
                rec["bal"] = Balance(rec["acct"].external_id, cur, clp(r.get("saldoFinal")),
                                     clp(r.get("saldoDisponible")) if r.get("saldoDisponible") is not None else None,
                                     date.today())
            movs = (r or {}).get("movimientos") or []
            dbg["pages"] += 1
            dbg["raw"] += len(movs)
            dbg.setdefault("keys", sorted((r or {}).keys()))
            if movs and "sample" not in dbg:
                import re as _re
                dbg["sample"] = {k: _re.sub(r"\d", "9", str(movs[0].get(k)))[:24]
                                 for k in ("fechaContable", "fecha", "fechaContableMovimiento", "tipo", "monto")}
            for i, m in enumerate(movs):
                d = to_date(m.get("fechaContable")) or to_date(m.get("fecha")) or to_date(m.get("fechaContableMovimiento"))
                if not d:
                    dbg["no_date"] += 1
                    continue
                if d < since:
                    dbg["old"] += 1
                    continue
                amt = abs(clp(m.get("monto")))
                if (m.get("tipo") or "").lower() == "cargo":
                    amt = -amt
                ext = str(m.get("id") or "") or _h(rec["acct"].external_id, d, m.get("descripcion"), amt, m.get("saldo"))
                if ext in seen:
                    ext = _h(ext, i)
                seen.add(ext)
                rec["txs"].append(BankTransaction(
                    external_id=ext, status="booked", value_date=d, booked_date=d, amount=amt, currency=cur,
                    description=(m.get("descripcion") or "").strip(), counterparty=None,
                    bank_reference=str(m.get("numeroDocumento") or "") or None,
                    raw={"canal": m.get("canal"), "tipo": m.get("tipo")}))
            pag = ((r or {}).get("pagina") or [{}])[0] or {}
            if str(pag.get("masPaginas")) not in MORE or not movs:
                break
            desde += len(movs)
            if rec["txs"] and min(t.value_date for t in rec["txs"]) < since:
                break

    def _card_bodies(self, it, nombre) -> list[dict[str, Any]]:
        marca, tipo = str(it.get("marca") or ""), str(it.get("tipo") or "")
        last4 = re.sub(r"\D", "", str(it.get("numero") or ""))[-4:]
        codes = [f"TN{marca[:1].upper()}", "TNM"] if marca else ["TNM"]
        names = [(nombre or "").strip(), (nombre or "").strip().ljust(30)]
        bodies, seen = [], set()
        for code in codes:
            for nom in names:
                key = (code, nom)
                if key in seen:
                    continue
                seen.add(key)
                bodies.append({"idTarjeta": it.get("idProducto"), "codigoProducto": code,
                               "tipoTarjeta": f"{marca} {tipo}  ", "mascara": f"****{last4}",
                               "nombreTitular": nom, "tipoCliente": "T" if it.get("titular", True) else "A"})
        return bodies

    @staticmethod
    def _try(c: PortalClient, url: str, bodies: list[dict[str, Any]]):
        last = None
        for b in bodies:
            try:
                return c.call("POST", url, b), b
            except BankError as exc:
                last = exc
                if "HTTP 5" not in str(exc) and "HTTP 4" not in str(exc):
                    raise
        raise last

    def _card(self, c: PortalClient, rec, nombre, since: date) -> None:
        cur = rec["acct"].currency
        bodies = self._card_bodies(rec["p"], nombre)
        rec["debug"] = {"bodies": len(bodies), "body_keys": {k: (str(v) and re.sub(r"\d", "9", str(v))[:30])
                                                            for k, v in bodies[0].items() if k != "nombreTitular"}}
        s, body = self._try(c, BASE + "tarjeta-credito-digital/saldo/obtener-saldo", bodies)
        s = s or {}
        rec["bal"] = Balance(rec["acct"].external_id, cur, -clp(s.get("cupoUtilizadoNacional")),
                             clp(s.get("cupoDisponibleNacional")), date.today())
        r = c.call("POST", BASE + "tarjeta-credito-digital/movimientos-no-facturados", body) or {}
        seen: dict[str, int] = {}
        for m in r.get("listaMovNoFactur") or []:
            d = to_date(m.get("fechaTransaccionString")) or to_date(m.get("fechaTransaccion"))
            if not d or d < since:
                continue
            amt = -clp(m.get("montoCompra"))
            base = _h(rec["acct"].external_id, m.get("fechaAutorizacion"), m.get("horaAutorizacion"),
                      m.get("codigoComercioTBK"), m.get("glosaTransaccion"), amt)
            n = seen.get(base, 0)
            seen[base] = n + 1
            cuota = None
            try:
                cuota = (int(m.get("numeroCuotas") or 0), int(m.get("numeroTotalCuotas") or 0))
            except ValueError:
                pass
            rec["txs"].append(BankTransaction(
                external_id=base if n == 0 else _h(base, n), status="booked", value_date=d, booked_date=d,
                amount=amt, currency=cur,
                description=(m.get("nombreComercio") or m.get("glosaTransaccion") or "").strip(),
                counterparty=(m.get("nombreComercio") or None),
                installment_number=cuota[0] if cuota and cuota[1] > 1 else None,
                installment_total=cuota[1] if cuota and cuota[1] > 1 else None,
                raw={"glosa": m.get("glosaTransaccion"), "rubro": m.get("rubroComercio")}))

    # ------------------------------------------------------------ contrato
    def get_accounts(self) -> list[BankAccount]:
        return [r["acct"] for r in self._load().values()]

    def get_balances(self, accounts: list[BankAccount]) -> list[Balance]:
        data = self._load()
        return [data[a.external_id]["bal"] for a in accounts if data.get(a.external_id, {}).get("bal")]

    def get_transactions(self, account: BankAccount, since: date) -> list[BankTransaction]:
        rec = self._load(since).get(account.external_id)
        if rec and rec.get("error") and not rec["txs"]:
            raise BankError(rec["error"])
        return [t for t in (rec["txs"] if rec else []) if t.value_date >= since]
