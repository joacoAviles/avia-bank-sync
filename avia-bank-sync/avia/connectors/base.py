"""Contrato común de conectores bancarios.

Cada conector declara sus capacidades reales (`capabilities`). El motor nunca
asume una capacidad que el banco no ofrece: por ejemplo, si un banco no
entrega pendientes, el motor no marca pendientes como revertidos.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


class Capability(str, enum.Enum):
    """Qué sabe entregar un conector (cuentas, saldos, pendientes, tarjetas, cuotas…)."""
    ACCOUNTS = "accounts"
    BALANCES = "balances"
    AVAILABLE_BALANCE = "available_balance"
    TRANSACTIONS = "transactions"
    PENDING_TRANSACTIONS = "pending_transactions"
    # El conector entrega la lista COMPLETA de pendientes vigentes en cada consulta
    # (permite detectar pendientes que desaparecen = revertidos).
    COMPLETE_PENDING_LIST = "complete_pending_list"
    PENDING_TO_BOOKED_REFERENCE = "pending_to_booked_reference"
    CREDIT_CARDS = "credit_cards"
    INSTALLMENTS = "installments"
    HISTORY = "history"
    REFRESH_AUTHORIZATION = "refresh_authorization"


class AuthorizationRequired(Exception):
    """El banco exige que el titular vuelva a autorizar el acceso."""


class ConnectorUnavailable(Exception):
    """No existe hoy un mecanismo autorizado y gratuito para este banco."""

    def __init__(self, bank_id: str, reason: str, doc: str):
        """Guarda banco, motivo y documento que explica el bloqueo."""
        super().__init__(reason)
        self.bank_id = bank_id
        self.reason = reason
        self.doc = doc


class BankError(Exception):
    """Error transitorio o de negocio reportado por el banco."""


@dataclass(frozen=True)
class BankAccount:
    """Cuenta o tarjeta tal como la entrega el banco."""
    external_id: str
    name: str
    account_type: str  # checking | vista | savings | credit_card | line_of_credit | other
    currency: str
    masked_number: str | None = None


@dataclass(frozen=True)
class Balance:
    """Saldo contable y disponible de una cuenta en una fecha."""
    external_account_id: str
    currency: str
    booked: Decimal | None  # saldo contable (convención Actual: deuda de tarjeta = negativo)
    available: Decimal | None = None
    as_of: date | None = None


@dataclass(frozen=True)
class BankTransaction:
    """Movimiento bancario normalizado (pendiente o contabilizado), con cuotas y moneda original."""
    external_id: str  # ID bancario estable. Obligatorio: sin él no se puede deduplicar con certeza.
    status: str  # pending | booked
    value_date: date
    amount: Decimal  # negativo = salida de dinero desde la perspectiva de la cuenta
    currency: str
    description: str
    booked_date: date | None = None
    counterparty: str | None = None
    kind: str = "other"
    pending_ref: str | None = None  # ID del pendiente al que corresponde este contabilizado
    bank_reference: str | None = None
    installment_number: int | None = None
    installment_total: int | None = None
    original_amount: Decimal | None = None
    original_currency: str | None = None
    fx_rate: Decimal | None = None
    fx_date: date | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class BankConnector(ABC):
    """Interfaz común de todos los conectores de banco."""
    bank_id: str = ""
    display_name: str = ""
    capabilities: frozenset[Capability] = frozenset()
    # Campos que el flujo Set up debe pedir (nunca contraseñas si existe OAuth oficial).
    setup_fields: tuple[dict[str, Any], ...] = ()

    def __init__(self, credentials: dict[str, Any] | None = None):
        """Recibe las credenciales ya descifradas."""
        self.credentials = credentials or {}

    @classmethod
    def availability(cls) -> dict[str, Any]:
        """Si el banco se puede usar hoy y, si no, por qué."""
        return {"available": True, "reason": None, "doc": None}

    @abstractmethod
    def authenticate(self) -> dict[str, Any]:
        """Valida la autorización. Devuelve credenciales actualizadas (p. ej. tokens renovados)."""

    @abstractmethod
    def get_accounts(self) -> list[BankAccount]:
        """Lista de cuentas del titular."""

    @abstractmethod
    def get_balances(self, accounts: list[BankAccount]) -> list[Balance]:
        """Saldos de las cuentas pedidas."""

    @abstractmethod
    def get_transactions(self, account: BankAccount, since: date) -> list[BankTransaction]:
        """Movimientos de una cuenta desde una fecha."""

    def refresh_authorization(self) -> dict[str, Any]:
        """Renueva la autorización; por defecto no se puede y pide reautorizar."""
        raise AuthorizationRequired("Este banco no permite renovar la autorización automáticamente")
