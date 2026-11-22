"""Traducción del modelo AVIA al contrato BankSyncResponse de Actual Budget 26.11.0.

Contrato verificado en el código de Actual (packages/loot-core/src/server/accounts/sync.ts):
- `transactions.all` ordenado del más reciente al más antiguo (el último se usa
  como fecha del saldo inicial).
- `transactionId` -> imported_id (deduplicación); `booked` -> cleared.
- `transactionAmount.amount` en unidades mayores; Actual aplica amountToInteger (x100).
  Actual guarda CLP con 2 decimales internos (shared/currencies.ts), por eso se
  envía con 2 decimales exactos, sin float.
- `startingBalance` = saldo actual en enteros x100.
- `payee` (opcional, extensión AVIA): lo fija el parche de loot-core cuando el
  movimiento es un pago de tarjeta emparejado => Actual lo registra como transferencia.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

TWO = Decimal("0.01")


def money_str(v: Decimal) -> str:
    """Monto con 2 decimales como texto."""
    return str(v.quantize(TWO, rounding=ROUND_HALF_UP))


def to_actual_integer(v: Decimal) -> int:
    """Monto a entero ×100 (formato interno de Actual)."""
    return int((v * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def build_notes(t: dict[str, Any]) -> str | None:
    """Notas para Actual: cuota n/m, moneda original y contraparte."""
    parts = []
    if t["installment_number"] and t["installment_total"]:
        parts.append(f"Cuota {t['installment_number']}/{t['installment_total']}")
    if t["original_currency"] and t["original_currency"] != t["currency"]:
        parts.append(f"Original {t['original_amount']} {t['original_currency']} "
                     f"(TC {t['fx_rate']} al {t['fx_date']})")
    if t["description"] and t["counterparty"] and t["counterparty"] != t["description"]:
        parts.append(t["description"])
    return " · ".join(parts) or None


def to_actual_transaction(t: dict[str, Any], transfer: tuple[str, str] | None) -> dict[str, Any]:
    """Un movimiento de AVIA al formato de bank sync de Actual (y transferencia si es pago de tarjeta)."""
    d: date = t["booked_date"] or t["value_date"]
    out = {
        "transactionId": t["lineage_id"],
        "booked": t["status"] == "booked",
        "date": d.isoformat(),
        "bookingDate": t["booked_date"].isoformat() if t["booked_date"] else None,
        "valueDate": t["value_date"].isoformat(),
        "payeeName": (t["counterparty"] or t["description"]).strip(),
        "notes": build_notes(t),
        "transactionAmount": {"amount": money_str(t["amount"]), "currency": t["currency"]},
        "aviaKind": t["kind"],
    }
    if transfer:
        # cuenta Actual de la contrapartida + imported_id de la contrapartida
        out["aviaTransferAccountId"], out["aviaTransferPeerId"] = transfer
    return out


def build_response(txns: list[dict[str, Any]], transfer_map: dict, balance: dict | None, currency: str) -> dict:
    """Respuesta completa para Actual: contabilizados, pendientes y saldos."""
    items = [to_actual_transaction(t, transfer_map.get(t["id"])) for t in txns]
    booked = [i for i in items if i["booked"]]
    pending = [i for i in items if not i["booked"]]
    balances = []
    starting = 0
    if balance and balance.get("booked") is not None:
        starting = to_actual_integer(balance["booked"])
        ref = balance["snapshot_date"].isoformat()
        balances.append({"balanceAmount": {"amount": money_str(balance["booked"]), "currency": currency},
                         "balanceType": "closingBooked", "referenceDate": ref})
        if balance.get("available") is not None:
            balances.append({"balanceAmount": {"amount": money_str(balance["available"]), "currency": currency},
                             "balanceType": "interimAvailable", "referenceDate": ref})
    return {
        "balances": balances,
        "startingBalance": starting,
        "transactions": {"all": items, "booked": booked, "pending": pending},
    }
