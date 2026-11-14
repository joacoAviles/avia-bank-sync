import os
from datetime import date

import psycopg
import pytest
from cryptography.fernet import Fernet

TEST_DSN = os.environ.get("AVIA_TEST_DATABASE_URL", "postgresql://avia:avia@localhost:5432/avia_test")
os.environ["AVIA_DATABASE_URL"] = TEST_DSN
os.environ.setdefault("AVIA_API_TOKEN", "t" * 40)
os.environ.setdefault("AVIA_ENCRYPTION_KEYS", Fernet.generate_key().decode())
os.environ["AVIA_FRESHNESS_HOURS"] = "12"

from avia import db  # noqa: E402
from avia.config import get_settings  # noqa: E402
from avia.connectors.sandbox import SandboxConnector  # noqa: E402
from avia.crypto import SecretBox  # noqa: E402
from avia.engine.sync import SyncEngine  # noqa: E402
from avia.service import AviaService  # noqa: E402


class Clock:
    def __init__(self, d: date):
        self.d = d

    def __call__(self) -> date:
        return self.d


@pytest.fixture()
def clock(monkeypatch):
    c = Clock(date(2026, 3, 10))
    monkeypatch.setattr(SandboxConnector, "today", staticmethod(c))
    return c


@pytest.fixture()
def fresh_db():
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    db.close_pool()
    db.migrate(TEST_DSN)
    db.init_pool(TEST_DSN, min_size=1, max_size=4)
    yield
    db.close_pool()


@pytest.fixture()
def service(fresh_db, clock):
    s = get_settings()
    engine = SyncEngine(s, SecretBox(s.encryption_keys), today=clock)
    svc = AviaService(s, engine)
    # en pruebas la sincronización es síncrona y determinista
    svc.start_background_sync = lambda trigger, ids=None, on_done=None: bool(engine.run(trigger, ids))
    return svc


def q(sql, *params):
    with db.tx() as conn:
        return conn.execute(sql, params).fetchall()
