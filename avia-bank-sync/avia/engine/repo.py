"""Operaciones SQL del motor. Todas reciben una conexión dentro de una transacción."""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg

from ..connectors.base import BankAccount, BankTransaction


def event(conn: psycopg.Connection, level: str, event_type: str, message: str, *, run_id=None,
          connection_id=None, bank_account_id=None, data: dict[str, Any] | None = None) -> None:
    """Registra un evento en la bitácora sync_events."""
    conn.execute(
        "INSERT INTO sync_events (run_id, connection_id, bank_account_id, level, event_type, message, data)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (run_id, connection_id, bank_account_id, level, event_type, message, json.dumps(data or {}, default=str)),
    )


def lineage_id(bank_id: str, account_external_id: str, external_id: str) -> str:
    """ID estable de un movimiento en Actual: avia:<banco>:<cuenta>:<id banco>."""
    return f"avia:{bank_id}:{account_external_id}:{external_id}"


def upsert_bank_account(conn, connection_id, acct: BankAccount) -> uuid.UUID:
    """Crea o actualiza una cuenta bancaria y devuelve su id."""
    row = conn.execute(
        """
        INSERT INTO bank_accounts (id, connection_id, external_id, name, account_type, currency, masked_number)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (connection_id, external_id) DO UPDATE
          SET name = EXCLUDED.name, account_type = EXCLUDED.account_type,
              masked_number = EXCLUDED.masked_number, active = true, updated_at = now()
        RETURNING id
        """,
        (uuid.uuid4(), connection_id, acct.external_id, acct.name, acct.account_type, acct.currency,
         acct.masked_number),
    ).fetchone()
    return row["id"]


def find_by_identifier(conn, bank_account_id, scheme: str, value: str) -> dict | None:
    """Busca un movimiento por uno de sus identificadores (bank_id, referencia…)."""
    return conn.execute(
        "SELECT t.* FROM transaction_identifiers i JOIN transactions t ON t.id = i.transaction_id"
        " WHERE i.bank_account_id = %s AND i.scheme = %s AND i.value = %s",
        (bank_account_id, scheme, value),
    ).fetchone()


def add_identifier(conn, transaction_id, bank_account_id, scheme: str, value: str) -> None:
    """Agrega un identificador a un movimiento (sin duplicar)."""
    conn.execute(
        "INSERT INTO transaction_identifiers (transaction_id, bank_account_id, scheme, value)"
        " VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (transaction_id, bank_account_id, scheme, value),
    )


def insert_transaction(conn, *, bank_account_id, lineage: str, t: BankTransaction, run_id,
                       needs_review=False, review_reason=None) -> uuid.UUID:
    """Inserta un movimiento nuevo con su linaje y marca de revisión."""
    tid = uuid.uuid4()
    conn.execute(
        """
        INSERT INTO transactions (id, bank_account_id, lineage_id, status, booked_date, value_date, amount, currency,
            description, counterparty, kind, installment_number, installment_total, original_amount,
            original_currency, fx_rate, fx_date, needs_review, review_reason, first_run_id, last_run_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (tid, bank_account_id, lineage, t.status, t.booked_date, t.value_date, t.amount, t.currency,
         t.description, t.counterparty, t.kind, t.installment_number, t.installment_total, t.original_amount,
         t.original_currency, t.fx_rate, t.fx_date, needs_review, review_reason, run_id, run_id),
    )
    add_identifier(conn, tid, bank_account_id, "bank_id", t.external_id)
    if t.bank_reference:
        add_identifier(conn, tid, bank_account_id, "bank_reference", t.bank_reference)
    return tid


TRACKED = ("status", "booked_date", "value_date", "amount", "currency", "description", "counterparty", "kind")


def apply_update(conn, existing: dict, t: BankTransaction, run_id) -> list[str]:
    """Actualiza los campos que cambiaron; nunca baja un contabilizado a pendiente."""
    changed = [f for f in TRACKED if _norm(existing[f]) != _norm(getattr(t, f))]
    if existing["status"] == "booked" and t.status == "pending":
        # nunca degradar un contabilizado a pendiente
        changed = [f for f in changed if f not in ("status", "booked_date")]
    if changed:
        sets = ", ".join(f"{f} = %s" for f in changed)
        conn.execute(
            f"UPDATE transactions SET {sets}, last_run_id = %s, updated_at = now() WHERE id = %s",
            (*[getattr(t, f) for f in changed], run_id, existing["id"]),
        )
    else:
        conn.execute("UPDATE transactions SET last_run_id = %s WHERE id = %s", (run_id, existing["id"]))
    return changed


def promote_pending(conn, pending: dict, t: BankTransaction, run_id) -> None:
    """Un pendiente pasa a contabilizado: misma fila, mismo lineage_id => Actual actualiza, no duplica."""
    conn.execute(
        """
        UPDATE transactions SET status = 'booked', booked_date = %s, value_date = %s, amount = %s,
            description = %s, counterparty = %s, kind = %s, last_run_id = %s, updated_at = now()
        WHERE id = %s
        """,
        (t.booked_date, t.value_date, t.amount, t.description, t.counterparty, t.kind, run_id, pending["id"]),
    )
    add_identifier(conn, pending["id"], pending["bank_account_id"], "bank_id", t.external_id)
    if t.bank_reference:
        add_identifier(conn, pending["id"], pending["bank_account_id"], "bank_reference", t.bank_reference)


def _norm(v):
    """Normaliza Decimal para comparar sin falsos cambios."""
    if isinstance(v, Decimal):
        return v.normalize()
    return v


def _desc_key(s: str | None) -> str:
    """Clave corta de descripción (10 alfanuméricos en mayúscula) para emparejar pendiente↔contabilizado."""
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())[:10]


def conservative_pending_match(conn, bank_account_id, t: BankTransaction) -> tuple[dict | None, bool]:
    """Busca el pendiente que corresponde a un contabilizado sin referencia bancaria.

    Devuelve (fila, ambiguo). Solo enlaza si hay exactamente UN candidato con
    mismo monto, misma moneda, fecha ±4 días y descripción compatible.
    """
    cands = conn.execute(
        """
        SELECT * FROM transactions
        WHERE bank_account_id = %s AND status = 'pending' AND amount = %s AND currency = %s
          AND value_date BETWEEN %s::date - 4 AND %s::date + 4
        """,
        (bank_account_id, t.amount, t.currency, t.value_date, t.value_date),
    ).fetchall()
    if not cands:
        return None, False
    key = _desc_key(t.description)
    exact = [c for c in cands if _desc_key(c["description"]) == key]
    if len(exact) == 1:
        return exact[0], False
    return None, True


def stale_pendings(conn, bank_account_id, since: date, seen_external_ids: set[str]) -> list[dict]:
    """Pendientes desde `since` que el banco ya no informa (posibles reversas)."""
    rows = conn.execute(
        """
        SELECT t.*, array_agg(i.value) FILTER (WHERE i.scheme = 'bank_id') AS bank_ids
        FROM transactions t JOIN transaction_identifiers i ON i.transaction_id = t.id
        WHERE t.bank_account_id = %s AND t.status = 'pending' AND t.value_date >= %s
        GROUP BY t.id
        """,
        (bank_account_id, since),
    ).fetchall()
    return [r for r in rows if not (set(r["bank_ids"] or []) & seen_external_ids)]


def get_cursor(conn, bank_account_id) -> date | None:
    """Última fecha contabilizada confirmada de una cuenta."""
    row = conn.execute("SELECT last_booked_date FROM sync_cursors WHERE bank_account_id = %s",
                       (bank_account_id,)).fetchone()
    return row["last_booked_date"] if row else None


def set_cursor(conn, bank_account_id, last_booked: date | None, run_id) -> None:
    """Avanza el cursor de la cuenta (nunca retrocede)."""
    conn.execute(
        """
        INSERT INTO sync_cursors (bank_account_id, last_booked_date, run_id) VALUES (%s,%s,%s)
        ON CONFLICT (bank_account_id) DO UPDATE SET
          last_booked_date = GREATEST(sync_cursors.last_booked_date, EXCLUDED.last_booked_date),
          confirmed_at = now(), run_id = EXCLUDED.run_id
        """,
        (bank_account_id, last_booked, run_id),
    )


def upsert_balance(conn, bank_account_id, snapshot_date: date, booked, available, currency) -> None:
    """Guarda el saldo del día y recalcula la diferencia con Actual."""
    conn.execute(
        """
        INSERT INTO balance_snapshots (bank_account_id, snapshot_date, booked, available, currency)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (bank_account_id, snapshot_date) DO UPDATE SET
          booked = EXCLUDED.booked, available = EXCLUDED.available, captured_at = now(),
          difference = CASE WHEN balance_snapshots.actual_calculated IS NULL THEN NULL
                            ELSE EXCLUDED.booked - balance_snapshots.actual_calculated END
        """,
        (bank_account_id, snapshot_date, booked, available, currency),
    )
