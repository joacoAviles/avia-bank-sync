from datetime import date
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet

from avia.crypto import SecretBox
from avia.engine.actual_format import money_str, to_actual_integer
from avia.logging_setup import _redact


def test_clp_conversion_is_exact():
    assert to_actual_integer(Decimal("15990")) == 1599000
    assert to_actual_integer(Decimal("-0.01")) == -1
    assert money_str(Decimal("-15990")) == "-15990.00"
    # caso que rompe con float
    assert to_actual_integer(Decimal("1.005")) == 101


def test_key_rotation():
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token = SecretBox([old]).encrypt({"a": 1})
    rotated_box = SecretBox([new, old])
    assert rotated_box.decrypt(token) == {"a": 1}
    t2 = rotated_box.rotate(token)
    assert SecretBox([new]).decrypt(t2) == {"a": 1}
    with pytest.raises(ValueError):
        SecretBox([new]).decrypt(token)


def test_logs_redact_secrets():
    out = _redact({"token": "x", "nested": {"password": "y", "ok": 1}, "rut": "1-9"})
    assert out == {"token": "[REDACTED]", "nested": {"password": "[REDACTED]", "ok": 1}, "rut": "[REDACTED]"}


def test_sandbox_is_deterministic(monkeypatch):
    from avia.connectors.sandbox import SandboxConnector
    monkeypatch.setattr(SandboxConnector, "today", staticmethod(lambda: date(2026, 3, 10)))
    c = SandboxConnector()
    a = c.get_transactions(c.get_accounts()[0], date(2026, 1, 1))
    b = c.get_transactions(c.get_accounts()[0], date(2026, 1, 1))
    assert a == b and all(isinstance(t.amount, Decimal) for t in a)
