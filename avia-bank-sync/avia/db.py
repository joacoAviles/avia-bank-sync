"""Acceso a PostgreSQL: pool, migraciones y locks consultivos."""

from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger("avia.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "database" / "migrations"

# Lock consultivo global: garantiza una sola sincronización a la vez,
# sin importar si la dispara el scheduler, Actual o un usuario.
SYNC_LOCK_KEY = int(hashlib.sha1(b"avia-bank-sync:sync").hexdigest()[:15], 16)
MIGRATION_LOCK_KEY = int(hashlib.sha1(b"avia-bank-sync:migrate").hexdigest()[:15], 16)

_pool: ConnectionPool | None = None


def init_pool(dsn: str, *, min_size: int = 1, max_size: int = 8) -> ConnectionPool:
    """Crea el pool de conexiones (filas como dict, sin autocommit)."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
        )
    return _pool


def close_pool() -> None:
    """Cierra el pool."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def pool() -> ConnectionPool:
    """Pool activo; falla si no se inicializó."""
    if _pool is None:
        raise RuntimeError("Pool no inicializado")
    return _pool


@contextmanager
def tx() -> Iterator[psycopg.Connection]:
    """Transacción atómica: commit al salir, rollback ante excepción."""
    with pool().connection() as conn:
        with conn.transaction():
            yield conn


def migrate(dsn: str) -> list[str]:
    """Aplica migraciones pendientes en orden, bajo lock, cada una atómica."""
    applied: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.stem in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
                log.info("migración aplicada", extra={"migration": path.stem})
                applied.append(path.stem)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
    return applied


@contextmanager
def sync_lock() -> Iterator[bool]:
    """Intenta tomar el lock de sincronización. Cede True si lo obtuvo.

    Usa una conexión dedicada (lock a nivel de sesión) que se mantiene
    mientras dura la sincronización. Si el proceso muere, PostgreSQL libera el lock.
    """
    conn = psycopg.connect(pool().conninfo, autocommit=True)
    try:
        got = conn.execute("SELECT pg_try_advisory_lock(%s)", (SYNC_LOCK_KEY,)).fetchone()[0]
        try:
            yield bool(got)
        finally:
            if got:
                conn.execute("SELECT pg_advisory_unlock(%s)", (SYNC_LOCK_KEY,))
    finally:
        conn.close()


def sync_lock_held() -> bool:
    """Si algún proceso tiene tomado el lock de sincronización."""
    with pool().connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory' AND granted"
            " AND ((classid::bigint << 32) | objid::bigint) = %s",
            (SYNC_LOCK_KEY,),
        ).fetchone()
        conn.rollback()
        return bool(row and row["n"])
