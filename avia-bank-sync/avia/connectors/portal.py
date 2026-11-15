"""Conectores por portal (usuario + clave del titular, login asistido).

Paso actual: LOGIN. La extracción (cuentas, saldos, movimientos) se implementa
en el siguiente paso, después de mapear cómo entrega los datos cada portal.
Mientras tanto, la sincronización registra «extracción pendiente» sin marcar
la conexión con error.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .base import Balance, BankAccount, BankConnector, BankTransaction


class ExtractionPending(Exception):
    """El login funciona, pero la lectura de datos de este portal aún no está implementada."""


class PortalConnector(BankConnector):
    auth_method = "portal_login"
    portal_id = ""
    setup_fields = (
        {"name": "rut", "label": "RUT", "type": "rut", "required": True},
        {"name": "password", "label": "Clave", "type": "password", "required": True},
    )

    def authenticate(self) -> dict[str, Any]:
        # La validez de la sesión se comprueba al extraer (siguiente paso).
        return self.credentials

    def _pending(self):
        raise ExtractionPending(f"{self.display_name}: login listo; la lectura de datos aún no está implementada")

    def get_accounts(self) -> list[BankAccount]:
        self._pending()

    def get_balances(self, accounts: list[BankAccount]) -> list[Balance]:
        self._pending()

    def get_transactions(self, account: BankAccount, since: date) -> list[BankTransaction]:
        self._pending()


class ItauPortal(PortalConnector):
    bank_id = portal_id = "itau"
    display_name = "Itaú Chile"

    @classmethod
    def availability(cls):
        return {"available": False, "doc": None,
                "reason": "Itaú no disponible: su portal bloquea los ingresos automatizados (Error 15)."}
