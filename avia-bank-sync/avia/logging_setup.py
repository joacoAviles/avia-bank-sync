"""Logs JSON estructurados. Nunca registrar credenciales ni detalle financiero completo."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

_REDACT_KEYS = re.compile(r"(password|passwd|secret|token|authorization|clave|rut|cookie)", re.I)
_STD = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def _redact(value):
    """Oculta valores de claves sensibles (password, token, rut…) en los logs."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _REDACT_KEYS.search(k) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """Formato de log JSON de una línea."""
    def format(self, record: logging.LogRecord) -> str:
        """Arma el JSON con hora, nivel, mensaje y extras redactados."""
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in _STD}
        if extras:
            payload.update(_redact(extras))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """Configura logs JSON a stdout y baja el ruido de uvicorn.access."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel("WARNING")
