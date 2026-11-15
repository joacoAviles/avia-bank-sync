"""Banco Ripley (web.bancoripley.cl): cuentas, saldos y movimientos.

Las respuestas de la API de Ripley viajan cifradas, pero la propia página las descifra y las lee con
JSON.parse. Este conector abre el portal con tu sesión (como tú), navega con los mismos clics y lee lo
que la página ya descifró para mostrártelo. No rompe ni evade cifrado ni controles: es lo que ves en pantalla.

Estructuras observadas (tools/grabador-json.mjs):
  - resumen de inicio: {checkingAccounts[{id,name,number,available,balance}], creditCards[{id,name,number,
    creditCardLines[{name,available,balance,limit}]}]}
  - movimientos de cuenta: [{id,date,amount,balance,description,branch,isDebit}]
  - movimientos de tarjeta: {indMasDatos, movements[{fechaFacturacion,descripcion,comercio,impFac,numeroCuota,
    impCuota,signo,...}]}
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from ..portal.banks import PORTALS
from ..portal.client import PortalClient
from .base import AuthorizationRequired, Balance, BankAccount, BankError, BankTransaction, Capability
from .bancochile import _h, clp, to_date
from .portal import PortalConnector

HOME = "https://web.bancoripley.cl/home"

# Engancha JSON.parse (antes de que cargue la página) y guarda lo ya descifrado que nos interesa.
HOOK_JS = """
(() => {
  window.__aviaCap = [];
  const orig = JSON.parse;
  JSON.parse = function (text, reviver) {
    const r = orig.call(this, text, reviver);
    try {
      if (r && typeof r === 'object') {
        const o = Array.isArray(r) ? (r[0] && typeof r[0] === 'object' ? r[0] : null) : r;
        if (o && ('isDebit' in o || 'checkingAccounts' in o || 'movements' in o || 'dueDate' in o || 'ResponseDepositAccount' in o)) {
          window.__aviaCap.push(r);
        }
      }
    } catch (e) {}
    return r;
  };
})();
"""


class RipleyPortal(PortalConnector):
    bank_id = portal_id = "ripley"
    display_name = "Banco Ripley"
    capabilities = frozenset({Capability.ACCOUNTS, Capability.BALANCES, Capability.AVAILABLE_BALANCE,
                              Capability.TRANSACTIONS, Capability.CREDIT_CARDS})

    def __init__(self, credentials=None):
        super().__init__(credentials)
        self._data: dict[str, dict[str, Any]] | None = None
        self.diagnostics: list = []
        self.debug: dict[str, Any] = {}

    def authenticate(self) -> dict[str, Any]:
        return self.credentials

    # ------------------------------------------------------------ utilidades de página
    @staticmethod
    def _cap(page, pred_js: str) -> list[Any]:
        return page.evaluate(f"(window.__aviaCap || []).filter({pred_js})")

    def _wait_cap(self, page, pred_js: str, timeout_s: int = 30) -> list[Any]:
        for _ in range(timeout_s * 2):
            got = self._cap(page, pred_js)
            if got:
                return got
            page.wait_for_timeout(500)
        return []

    @staticmethod
    def _click_menu(page, label: str) -> None:
        pat = re.compile(rf"^\s*{re.escape(label)}\s*$", re.I)
        for loc in (page.locator("app-menu-item button.menu-item").filter(has_text=pat),
                    page.get_by_role("button", name=pat), page.get_by_text(pat)):
            try:
                loc.first.click(timeout=8000)
                return
            except Exception:  # noqa: BLE001
                continue
        raise BankError(f"Banco Ripley: no encontré «{label}» en el menú")

    # ------------------------------------------------------------ extracción
    def _load(self, since: date | None = None) -> dict[str, dict[str, Any]]:
        if self._data is not None:
            return self._data
        since = since or (date.today() - timedelta(days=90))
        data: dict[str, dict[str, Any]] = {}
        portal = PORTALS[self.portal_id]
        with PortalClient(portal, self.credentials, "proxy.miportalbeta.bancoripley.cl", init_script=HOOK_JS) as c:
            self.diagnostics = c.log
            page = c.page
            summ = self._wait_cap(page, "o => !Array.isArray(o) && 'checkingAccounts' in o", 40)
            if not summ:
                page.goto(HOME, wait_until="domcontentloaded", timeout=45000)
                summ = self._wait_cap(page, "o => !Array.isArray(o) && 'checkingAccounts' in o", 40)
            if not summ:
                raise BankError("Banco Ripley: no pude leer el resumen de productos (la página no entregó datos)")
            s = summ[-1]
            self.debug["summary_keys"] = sorted(s.keys())
            for a in s.get("checkingAccounts") or []:
                num = str(a.get("number") or "")
                acct = BankAccount(str(a["id"]), a.get("name") or "Cuenta Corriente", "checking", "CLP",
                                   f"****{re.sub(chr(92) + 'D', '', num)[-4:]}" if num else None)
                data[acct.external_id] = {
                    "acct": acct, "txs": [], "error": None,
                    "bal": Balance(acct.external_id, "CLP", clp(a.get("balance")), clp(a.get("available")),
                                   date.today())}
            for cc in s.get("creditCards") or []:
                num = re.sub(r"\D", "", str(cc.get("number") or ""))
                acct = BankAccount(str(cc["id"]), cc.get("name") or "Tarjeta de Crédito", "credit_card", "CLP",
                                   f"****{num[-4:]}" if num else None)
                lines = cc.get("creditCardLines") or []
                self.debug["card_lines"] = [{"name": l.get("name"), "limit": l.get("limit"),
                                              "balance": l.get("balance"), "available": l.get("available")}
                                             for l in lines]
                main = max(lines, key=lambda l: clp(l.get("limit")), default=None)
                bal = None
                if main:
                    bal = Balance(acct.external_id, "CLP", -abs(clp(main.get("balance"))),
                                  clp(main.get("available")), date.today())
                data[acct.external_id] = {"acct": acct, "txs": [], "bal": bal, "error": None}

            checking = [r for r in data.values() if r["acct"].account_type == "checking"]
            cards = [r for r in data.values() if r["acct"].account_type == "credit_card"]
            if checking:  # varias cuentas: se lee la primera que muestra el menú (limitación conocida)
                try:
                    self._read_checking(page, checking[0], since)
                except BankError as exc:
                    checking[0]["error"] = str(exc)
            if cards:
                try:
                    self._read_card(page, cards[0], since)
                except BankError as exc:
                    cards[0]["error"] = str(exc)
            self._read_deposits(page, data)
            self.diagnostics = c.log
        self._data = data
        return data

    def _read_deposits(self, page, data) -> None:
        """Depósitos a plazo: una cuenta «Depósitos a plazo» con el total al vencimiento en CLP.

        Aún no hay muestra de un depósito vigente: el saldo sale de Deposit.maturityAmountTotalCLP y el
        detalle de DepositTransactionReference se deja en el diagnóstico para afinar el mapeo.
        """
        acct = BankAccount("ripley-dap", "Depósitos a plazo", "savings", "CLP", "DAP")
        rec = {"acct": acct, "txs": [], "bal": None, "error": None}
        data[acct.external_id] = rec
        try:
            page.goto(f"{HOME}/depositos-a-plazo", wait_until="domcontentloaded", timeout=45000)
            pred = "o => !Array.isArray(o) && o.ResponseDepositAccount && o.ResponseDepositAccount.Deposit"
            got = self._wait_cap(page, pred, 25)
            page.wait_for_timeout(2000)
            allr = self._cap(page, "o => !Array.isArray(o) && !!o.ResponseDepositAccount")
            total, items = None, []
            for g in allr:
                r = g["ResponseDepositAccount"]
                dep = r.get("Deposit")
                if isinstance(dep, dict) and dep.get("maturityAmountTotalCLP") is not None:
                    total = clp(dep.get("maturityAmountTotalCLP"))
                items += r.get("DepositTransactionReference") or []
            self.debug["dap_items"] = len(items)
            self.debug["dap_item_keys"] = sorted({k for it in items if isinstance(it, dict) for k in it})[:40]
            if total is None and not got:
                rec["error"] = "Banco Ripley: la página de depósitos no entregó datos"
                return
            rec["bal"] = Balance(acct.external_id, "CLP", total or Decimal(0), None, date.today())
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"Banco Ripley: depósitos a plazo ({type(exc).__name__})"

    def _read_checking(self, page, rec, since: date) -> None:
        page.goto(f"{HOME}/account-balance/accounts;id={rec['acct'].external_id}", wait_until="domcontentloaded",
                  timeout=45000)
        got = self._wait_cap(page, "o => Array.isArray(o) && o[0] && 'isDebit' in o[0]", 30)
        if not got:
            raise BankError("Banco Ripley: la cuenta corriente no entregó movimientos")
        seen: dict[str, int] = {}
        items = [m for arr in got for m in arr]
        self.debug["acct_items"] = len(items)
        for m in items:
            d = to_date(m.get("date"))
            if not d or d < since:
                continue
            amt = abs(clp(m.get("amount")))
            if m.get("isDebit"):
                amt = -amt
            base = _h(rec["acct"].external_id, m.get("id"), d, amt, m.get("balance"), m.get("description"))
            n = seen.get(base, 0)
            seen[base] = n + 1
            rec["txs"].append(BankTransaction(
                external_id=base if n == 0 else _h(base, n), status="booked", value_date=d, booked_date=d,
                amount=amt, currency="CLP", description=(m.get("description") or "").strip(),
                raw={"branch": m.get("branch")}))
        if rec["txs"]:  # saldo de la última línea si el resumen no lo trajo
            pass

    def _read_card(self, page, rec, since: date) -> None:
        page.goto(f"{HOME}/account-balance/credit-cards;id={rec['acct'].external_id}", wait_until="domcontentloaded",
                  timeout=45000)
        pred = "o => !Array.isArray(o) && Array.isArray(o.movements)"
        got = list(self._wait_cap(page, pred, 30))
        if not got:
            raise BankError("Banco Ripley: la tarjeta no entregó movimientos")
        try:  # además, la pestaña de movimientos facturados
            n0 = len(got)
            page.get_by_text(re.compile(r"^\s*Facturados\s*$", re.I)).first.click(timeout=8000)
            for _ in range(24):
                page.wait_for_timeout(500)
                if len(self._cap(page, pred)) > n0:
                    break
            got = self._cap(page, pred)
        except Exception:  # noqa: BLE001
            pass
        self.debug["card_batches"] = len(got)
        self.debug["card_more"] = [str(g.get("indMasDatos")) for g in got]
        seen: dict[str, int] = {}
        keys: set[str] = set()
        for g in got:
            for m in g.get("movements") or []:
                d = to_date(m.get("fechaFacturacion"))
                if not d or d < since:
                    continue
                amt = abs(clp(m.get("impFac")))
                if str(m.get("signo")).strip() != "-":  # "+" = cargo (compra) → sale dinero
                    amt = -amt
                base = _h(rec["acct"].external_id, d, m.get("descripcion"), m.get("comercio"), amt,
                          m.get("numeroCuota"), m.get("impCuota"), m.get("pan"))
                if base in keys and (g is not got[0]):
                    pass
                n = seen.get(base, 0)
                seen[base] = n + 1
                cuota = int(m.get("numeroCuota") or 0)
                rec.setdefault("raw_keys", set()).add(base)
                rec["txs"].append((g is got[0], base, n, BankTransaction(
                    external_id=base if n == 0 else _h(base, n), status="booked", value_date=d, booked_date=d,
                    amount=amt, currency="CLP",
                    description=((m.get("comercio") or m.get("descripcion") or "").strip()),
                    counterparty=(m.get("comercio") or None) or None,
                    installment_number=cuota if cuota > 1 else None,
                    raw={"descripcion": m.get("descripcion"), "signo": m.get("signo"),
                         "posteado": m.get("posteado")})))
        # Lotes superpuestos (no facturados / facturados) repiten movimientos: quedarse con uno por huella.
        uniq, seen_ids = [], set()
        for _first, base, n, tx in rec["txs"]:
            if tx.external_id in seen_ids:
                continue
            seen_ids.add(tx.external_id)
            uniq.append(tx)
        rec["txs"] = uniq

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
