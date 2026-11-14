"""Registro de conectores."""

from __future__ import annotations

from .base import BankConnector
from .portal import BancoChilePortal, ItauPortal, RipleyPortal
from .sandbox import SandboxConnector

REGISTRY: dict[str, type[BankConnector]] = {
    "sandbox": SandboxConnector,
    "banco_chile": BancoChilePortal,
    "itau": ItauPortal,
    "ripley": RipleyPortal,
}


def get_connector_class(key: str) -> type[BankConnector]:
    try:
        return REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"Conector desconocido: {key}") from exc
