"""Banco ficticio determinista para pruebas de punta a punta.

Datos 100% inventados. Reproduce los casos difíciles que debe soportar el motor:
- pendientes que pasan a contabilizados con un ID nuevo (y referencia al pendiente),
- pendientes que se revierten (desaparecen sin contabilizarse),
- compras en cuotas, intereses y comisiones de tarjeta,
- pago de tarjeta que sale de la cuenta corriente y entra a la tarjeta,
- saldo contable distinto del disponible.

El "día de hoy" es inyectable (SandboxConnector.today) para pruebas.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo
from datetime import datetime

from .base import (
    AuthorizationRequired,
    Balance,
    BankAccount,
    BankConnector,
    BankError,
    BankTransaction,
    Capability,
)

ANCHOR = date(2026, 1, 1)
PENDING_DAYS = 2  # un movimiento queda pendiente 2 días antes de contabilizarse

CHECKING = BankAccount("SBX-CC-0001", "Cuenta Corriente Sandbox", "checking", "CLP", "****0001")
CARD = BankAccount("SBX-TC-0002", "Tarjeta de Crédito Sandbox", "credit_card", "CLP", "****4242")

OPENING = {CHECKING.external_id: Decimal("1500000"), CARD.external_id: Decimal("0")}

MERCHANTS = [
    ("COPEC LAS CONDES", 18000, 45000, "purchase"),
    ("JUMBO KENNEDY", 12000, 90000, "purchase"),
    ("UBER TRIP", 3500, 14000, "purchase"),
    ("LIDER EXPRESS", 2500, 25000, "purchase"),
    ("STARBUCKS", 3200, 6500, "purchase"),
]


def _h(*parts: Any) -> int:
    """Hash entero estable para generar datos ficticios deterministas."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _santiago_today() -> date:
    """Fecha de hoy en Santiago."""
    return datetime.now(ZoneInfo("America/Santiago")).date()


class SandboxConnector(BankConnector):
    """Banco ficticio determinista para pruebas: cuenta corriente y tarjeta con pendientes, reversas y pagos."""
    bank_id = "sandbox"
    display_name = "AVIA Sandbox (datos ficticios)"
    capabilities = frozenset(
        {
            Capability.ACCOUNTS,
            Capability.BALANCES,
            Capability.AVAILABLE_BALANCE,
            Capability.TRANSACTIONS,
            Capability.PENDING_TRANSACTIONS,
            Capability.COMPLETE_PENDING_LIST,
            Capability.PENDING_TO_BOOKED_REFERENCE,
            Capability.CREDIT_CARDS,
            Capability.INSTALLMENTS,
            Capability.HISTORY,
            Capability.REFRESH_AUTHORIZATION,
        }
    )
    setup_fields = (
        {"name": "label", "label": "Nombre de la conexión", "type": "text", "required": False},
    )
    today: Callable[[], date] = staticmethod(_santiago_today)

    # ---- autenticación -------------------------------------------------
    def authenticate(self) -> dict[str, Any]:
        """Simula expiración (90 días) y fallas según `fail_mode`."""
        mode = self.credentials.get("fail_mode")
        if mode == "auth":
            raise AuthorizationRequired("Sandbox: autorización expirada (simulada)")
        if mode == "bank_error":
            raise BankError("Sandbox: servicio bancario no disponible (simulado)")
        token_day = self.credentials.get("token_issued")
        if token_day and (self.today() - date.fromisoformat(token_day)).days > 90:
            raise AuthorizationRequired("Sandbox: el token de acceso caducó (90 días)")
        return {**self.credentials, "token_issued": self.credentials.get("token_issued") or self.today().isoformat()}

    def refresh_authorization(self) -> dict[str, Any]:
        """Renueva el token ficticio y quita la falla simulada."""
        creds = {k: v for k, v in self.credentials.items() if k != "fail_mode"}
        creds["token_issued"] = self.today().isoformat()
        return creds

    # ---- datos ----------------------------------------------------------
    def get_accounts(self) -> list[BankAccount]:
        """Cuenta corriente y tarjeta ficticias."""
        return [CHECKING, CARD]

    def _events(self, until: date) -> list[dict[str, Any]]:
        """Genera todos los eventos de negocio desde ANCHOR hasta `until` (incluido)."""
        events: list[dict[str, Any]] = []
        d = ANCHOR
        while d <= until:
            # sueldo: día 28 de cada mes
            if d.day == 28:
                events.append(dict(acct=CHECKING, day=d, seq=0, amount=Decimal("2350000"),
                                   desc="TRANSFERENCIA DE AVIA ROCKETS SPA REMUNERACION", cp="AVIA ROCKETS SPA",
                                   kind="deposit"))
            # pago de tarjeta: día 5, monto fijo determinista
            if d.day == 5 and d > ANCHOR:
                amt = Decimal(150000 + (_h("pay", d) % 8) * 10000)
                ref = f"PAGO-{d.isoformat()}"
                events.append(dict(acct=CHECKING, day=d, seq=1, amount=-amt, desc="PAGO TARJETA DE CREDITO ****4242",
                                   cp="TARJETA ****4242", kind="card_payment", ref=ref))
                events.append(dict(acct=CARD, day=d, seq=1, amount=amt, desc="PAGO RECIBIDO GRACIAS",
                                   cp=None, kind="payment", ref=ref))
            # suscripción mensual en tarjeta
            if d.day == 12:
                events.append(dict(acct=CARD, day=d, seq=2, amount=Decimal("-9490"), desc="NETFLIX.COM",
                                   cp="NETFLIX", kind="purchase"))
            # interés y comisión mensual
            if d.day == 20:
                events.append(dict(acct=CARD, day=d, seq=3, amount=Decimal("-4120"), desc="INTERESES ROTATIVOS",
                                   cp=None, kind="interest"))
                events.append(dict(acct=CARD, day=d, seq=4, amount=Decimal("-1990"), desc="COMISION MANTENCION",
                                   cp=None, kind="fee"))
            # compra en cuotas iniciada el 3 de febrero: 6 cuotas, cargo el día 3
            if d.day == 3 and date(2026, 2, 3) <= d:
                n = (d.year - 2026) * 12 + d.month - 2 + 1
                if 1 <= n <= 6:
                    events.append(dict(acct=CARD, day=d, seq=5, amount=Decimal("-99990"),
                                       desc=f"PARIS PARQUE ARAUCO CUOTA {n:02d}/06", cp="PARIS", kind="installment",
                                       inst=(n, 6)))
            # compras cotidianas
            for i in range(_h("n", d) % 3):
                name, lo, hi, kind = MERCHANTS[_h("m", d, i) % len(MERCHANTS)]
                amt = Decimal(lo + (_h("a", d, i) % (hi - lo)) // 10 * 10)
                acct = CARD if _h("acct", d, i) % 2 else CHECKING
                events.append(dict(acct=acct, day=d, seq=10 + i, amount=-amt, desc=name, cp=name.split()[0],
                                   kind=kind, reversible=True))
            d += timedelta(days=1)
        return events

    def _is_reversed(self, ev: dict[str, Any]) -> bool:
        # ~1 de cada 25 compras cotidianas es una retención que el comercio anula
        """~1 de cada 25 compras cotidianas es una retención que se anula."""
        return bool(ev.get("reversible")) and _h("rev", ev["day"], ev["seq"]) % 25 == 0

    def get_transactions(self, account: BankAccount, since: date) -> list[BankTransaction]:
        """Movimientos ficticios desde `since` (pendientes que luego se contabilizan)."""
        today = self.today()
        out: list[BankTransaction] = []
        for ev in self._events(today):
            if ev["acct"].external_id != account.external_id or ev["day"] < since:
                continue
            base = f"{ev['day'].strftime('%Y%m%d')}{ev['seq']:02d}"
            pending_id = f"P{base}"
            age = (today - ev["day"]).days
            reversed_ = self._is_reversed(ev)
            common = dict(
                value_date=ev["day"],
                amount=ev["amount"],
                currency="CLP",
                description=ev["desc"],
                counterparty=ev["cp"],
                kind=ev["kind"],
                bank_reference=ev.get("ref"),
                installment_number=ev.get("inst", (None, None))[0],
                installment_total=ev.get("inst", (None, None))[1],
            )
            if age < PENDING_DAYS:
                out.append(BankTransaction(external_id=pending_id, status="pending", **common))
            elif not reversed_:
                out.append(BankTransaction(
                    external_id=f"B{base}", status="booked", booked_date=ev["day"] + timedelta(days=1 if ev["kind"] == "purchase" else 0),
                    pending_ref=pending_id, **common))
            # revertido y vencido: el banco simplemente deja de informarlo
        return out

    def _booked_balance(self, account: BankAccount, as_of: date) -> Decimal:
        """Saldo contable a una fecha: apertura + movimientos ya contabilizados."""
        total = OPENING[account.external_id]
        for ev in self._events(as_of):
            if ev["acct"].external_id == account.external_id and (as_of - ev["day"]).days >= PENDING_DAYS \
                    and not self._is_reversed(ev):
                total += ev["amount"]
        return total

    def get_balances(self, accounts: list[BankAccount]) -> list[Balance]:
        """Saldo contable y disponible (descontando pendientes)."""
        today = self.today()
        out = []
        for acct in accounts:
            booked = self._booked_balance(acct, today)
            pending = sum(
                (ev["amount"] for ev in self._events(today)
                 if ev["acct"].external_id == acct.external_id and (today - ev["day"]).days < PENDING_DAYS),
                Decimal(0),
            )
            available = booked + pending
            if acct.account_type == "credit_card":
                available = Decimal("2000000") + booked + pending  # cupo disponible
            out.append(Balance(acct.external_id, acct.currency, booked, available, today))
        return out

    def opening_balance(self, account: BankAccount) -> Decimal:
        """Saldo de apertura de la cuenta ficticia."""
        return OPENING[account.external_id]
