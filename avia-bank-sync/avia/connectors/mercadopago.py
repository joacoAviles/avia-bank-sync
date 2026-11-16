"""Mercado Pago (cuenta personal) por la API oficial de reportes.

Autorización: Access Token del titular (Mercado Pago Developers → Tus integraciones →
credenciales de producción). No se usa RUT ni clave. El token se guarda cifrado.

Movimientos: «Reporte de liberaciones» (release_report). Es asíncrono: se solicita un
rango de fechas, se espera a que el reporte aparezca en la lista y se descarga el CSV.
Cada fila es un movimiento real del saldo (crédito o débito), con BALANCE_AMOUNT.
Los nombres de columnas se leen por encabezado, así que el orden no importa.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .base import (
    AuthorizationRequired,
    Balance,
    BankAccount,
    BankConnector,
    BankError,
    BankTransaction,
    Capability,
)

API = "https://api.mercadopago.com"
SKIP_RECORD_TYPES = {"initial_available_balance", "total", "available_balance", "balance"}
POLL_SECONDS = 5
POLL_TRIES = 36  # ~3 minutos


def _dec(v: Any) -> Decimal:
    s = str(v or "").strip().replace(" ", "")
    if not s:
        return Decimal("0")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def _d(v: str) -> date:
    return datetime.fromisoformat(v.strip().replace("Z", "+00:00")).date() if "T" in v else date.fromisoformat(v.strip()[:10])


def parse_release_csv(text: str) -> tuple[list[BankTransaction], Decimal | None]:
    """Devuelve (movimientos, último saldo informado por el reporte)."""
    text = text.lstrip("﻿")
    first = text.splitlines()[0] if text.strip() else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
    out: list[BankTransaction] = []
    last_balance: Decimal | None = None
    seen: dict[str, int] = {}
    for r in rows:
        r = {(k or "").strip().upper(): (v or "").strip() for k, v in r.items()}
        rtype = r.get("RECORD_TYPE", "").lower()
        if r.get("BALANCE_AMOUNT"):
            last_balance = _dec(r["BALANCE_AMOUNT"])
        if rtype in SKIP_RECORD_TYPES or not r.get("DATE"):
            continue
        amount = _dec(r.get("NET_CREDIT_AMOUNT")) - _dec(r.get("NET_DEBIT_AMOUNT"))
        if amount == 0:
            continue
        desc = r.get("DESCRIPTION") or rtype or "Mercado Pago"
        base = f"{r.get('SOURCE_ID','')}|{r.get('DATE')}|{desc}|{amount}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        ext = "MP-" + hashlib.sha256(f"{base}|{n}".encode()).hexdigest()[:20]
        d = _d(r["DATE"])
        out.append(BankTransaction(
            external_id=ext, status="booked", value_date=d, booked_date=d, amount=amount, currency="CLP",
            description=desc, counterparty=r.get("EXTERNAL_REFERENCE") or None,
            kind=rtype or "other", bank_reference=r.get("SOURCE_ID") or None,
            raw={k: v for k, v in r.items() if k in ("RECORD_TYPE", "SOURCE_ID", "PAYMENT_METHOD", "ORDER_ID")},
        ))
    return out, last_balance


class MercadoPagoConnector(BankConnector):
    bank_id = "mercado-pago"
    display_name = "Mercado Pago"
    auth_method = "access_token"
    capabilities = frozenset({Capability.ACCOUNTS, Capability.BALANCES, Capability.TRANSACTIONS, Capability.HISTORY})
    setup_fields = (
        {"name": "access_token", "label": "Access Token (producción)", "type": "password", "required": False},
    )
    # Inyectable en pruebas
    client_factory = staticmethod(lambda: httpx.Client(base_url=API, timeout=60))
    sleep = staticmethod(time.sleep)

    def __init__(self, credentials: dict[str, Any] | None = None):
        super().__init__(credentials)
        self._last_balance: Decimal | None = None

    # ------------------------------------------------------------------
    def _token(self) -> str:
        # La UI de Actual no tiene campo para el token: se entrega una sola vez por AVIA_MP_ACCESS_TOKEN
        # (.env del servidor) y desde ahí queda guardado cifrado en la base; luego se puede borrar del .env.
        return (self.credentials.get("access_token") or os.environ.get("AVIA_MP_ACCESS_TOKEN") or "").strip()

    def _client(self) -> httpx.Client:
        tok = self._token()
        if not tok:
            raise AuthorizationRequired("Falta el Access Token: ponlo en AVIA_MP_ACCESS_TOKEN en el .env del servidor y recrea avia-api")
        c = self.client_factory()
        c.headers["Authorization"] = f"Bearer {tok}"
        c.headers["accept"] = "application/json"
        return c

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code in (401, 403):
            raise AuthorizationRequired("Mercado Pago rechazó el Access Token (inválido, vencido o sin permiso de reportes)")
        if r.status_code >= 400:
            raise BankError(f"Mercado Pago respondió {r.status_code}: {r.text[:200]}")
        return r

    def authenticate(self) -> dict[str, Any]:
        with self._client() as c:
            me = self._check(c.get("/users/me")).json()
        site = str(me.get("site_id", ""))
        if site and site != "MLC":
            raise AuthorizationRequired(f"La cuenta es de otro país ({site}); se esperaba Mercado Pago Chile (MLC)")
        self.credentials = {**self.credentials, "access_token": self._token(), "user_id": str(me.get("id", ""))}
        return self.credentials

    def get_accounts(self) -> list[BankAccount]:
        uid = self.credentials.get("user_id") or self.authenticate()["user_id"]
        return [BankAccount(external_id=uid, name="Mercado Pago", account_type="vista", currency="CLP",
                            masked_number=f"****{uid[-4:]}")]

    def get_balances(self, accounts: list[BankAccount]) -> list[Balance]:
        acc = accounts[0]
        bal: Decimal | None = None
        avail: Decimal | None = None
        with self._client() as c:
            r = c.get(f"/users/{acc.external_id}/mercadopago_account/balance")
            if r.status_code == 200:
                j = r.json()
                bal = _dec(j.get("total_amount"))
                avail = _dec(j.get("available_balance"))
        if bal is None:
            bal = self._last_balance  # saldo del último reporte, si ya se descargó
        return [Balance(acc.external_id, "CLP", bal, avail, date.today())]

    # ------------------------------------------------------------------
    def _ensure_config(self, c: httpx.Client) -> None:
        r = c.get("/v1/account/release_report/config")
        if r.status_code == 200:
            return
        body = {"file_name_prefix": "avia-release", "display_timezone": "GMT-04", "report_translation": "es",
                "include_withdrawal_at_end": True, "execute_after_withdrawal": False,
                "check_available_balance": False, "compensate_detail": False, "scheduled": False}
        rr = c.post("/v1/account/release_report/config", json=body)
        if rr.status_code not in (200, 201, 409):
            self._check(rr)

    def _fetch_range(self, c: httpx.Client, begin: date, end: date) -> str:
        b = datetime(begin.year, begin.month, begin.day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        e = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._check(c.post("/v1/account/release_report", json={"begin_date": b, "end_date": e}))
        for _ in range(POLL_TRIES):
            self.sleep(POLL_SECONDS)
            lst = self._check(c.get("/v1/account/release_report/list")).json()
            items = lst if isinstance(lst, list) else lst.get("results", [])
            match = [i for i in items if str(i.get("begin_date", ""))[:10] == b[:10]
                     and str(i.get("end_date", ""))[:10] == e[:10] and i.get("file_name")]
            if match:
                match.sort(key=lambda i: str(i.get("date_created", "")), reverse=True)
                return self._check(c.get(f"/v1/account/release_report/{match[0]['file_name']}")).text
        raise BankError("Mercado Pago no terminó de generar el reporte a tiempo; se reintentará en la próxima sincronización")

    def get_transactions(self, account: BankAccount, since: date) -> list[BankTransaction]:
        today = date.today()
        since = max(since, today - timedelta(days=365 * 2))
        txs: list[BankTransaction] = []
        with self._client() as c:
            self._ensure_config(c)
            cur = since
            while cur <= today:  # la API limita el rango; se pide por tramos de 60 días
                end = min(cur + timedelta(days=59), today)
                part, bal = parse_release_csv(self._fetch_range(c, cur, end))
                txs.extend(part)
                if bal is not None:
                    self._last_balance = bal
                cur = end + timedelta(days=1)
        return txs
