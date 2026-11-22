"""Registro de conectores."""

from __future__ import annotations

from .base import BankConnector
from .bancochile import BancoChilePortal
from .mercadopago import MercadoPagoConnector
from .portal import BancoEstadoPortal, ItauPortal
from .ripley import RipleyPortal
from .sandbox import SandboxConnector

REGISTRY: dict[str, type[BankConnector]] = {
    "sandbox": SandboxConnector,
    "banco_chile": BancoChilePortal,
    "itau": ItauPortal,
    "ripley": RipleyPortal,
    "banco_estado": BancoEstadoPortal,
    "mercado_pago": MercadoPagoConnector,
}


def get_connector_class(key: str) -> type[BankConnector]:
    """Clase del conector por su clave de REGISTRY (p. ej. 'banco_chile')."""
    try:
        return REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"Conector desconocido: {key}") from exc
