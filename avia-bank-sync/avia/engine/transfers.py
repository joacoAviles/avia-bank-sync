"""Emparejamiento de pagos de tarjeta (salida en cuenta corriente <-> abono en tarjeta).

Se empareja solo cuando el resultado es inequívoco. Actual convierte la salida
en transferencia (payee de transferencia) y concilia el abono de la tarjeta, por lo
que el pago NO aparece como gasto adicional.
"""

from __future__ import annotations

from . import repo


def pair_card_payments(conn, run_id) -> int:
    """Empareja pagos de tarjeta (salida en cuenta ↔ abono en tarjeta) como transferencia."""
    outs = conn.execute(
        """
        SELECT t.*, i.value AS ref FROM transactions t
        JOIN bank_accounts a ON a.id = t.bank_account_id
        LEFT JOIN transaction_identifiers i ON i.transaction_id = t.id AND i.scheme = 'bank_reference'
        WHERE t.kind = 'card_payment' AND t.amount < 0 AND t.transfer_peer_id IS NULL
          AND t.status = 'booked' AND a.account_type <> 'credit_card'
        """
    ).fetchall()
    paired = 0
    for out in outs:
        cands = conn.execute(
            """
            SELECT t.*, i.value AS ref FROM transactions t
            JOIN bank_accounts a ON a.id = t.bank_account_id
            LEFT JOIN transaction_identifiers i ON i.transaction_id = t.id AND i.scheme = 'bank_reference'
            WHERE t.kind = 'payment' AND a.account_type = 'credit_card' AND t.transfer_peer_id IS NULL
              AND t.status = 'booked' AND t.amount = %s AND t.currency = %s
              AND t.value_date BETWEEN %s::date - 3 AND %s::date + 3
            """,
            (-out["amount"], out["currency"], out["value_date"], out["value_date"]),
        ).fetchall()
        if out["ref"]:
            by_ref = [c for c in cands if c["ref"] == out["ref"]]
            cands = by_ref or cands
        if len(cands) == 1:
            peer = cands[0]
            conn.execute("UPDATE transactions SET transfer_peer_id = %s, updated_at = now() WHERE id = %s",
                         (peer["id"], out["id"]))
            conn.execute("UPDATE transactions SET transfer_peer_id = %s, updated_at = now() WHERE id = %s",
                         (out["id"], peer["id"]))
            paired += 1
        elif len(cands) > 1:
            repo.event(conn, "warning", "ambiguous_card_payment",
                       "Pago de tarjeta con varios abonos posibles; queda sin emparejar",
                       run_id=run_id, bank_account_id=out["bank_account_id"], data={"lineage_id": out["lineage_id"]})
    return paired
