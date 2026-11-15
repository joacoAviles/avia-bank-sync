"""Configuración por variables de entorno. Sin valores secretos por defecto."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Falta la variable de entorno obligatoria {name}")
    return value


def _read_secret(name: str) -> str | None:
    """Admite NAME o NAME_FILE (Docker secrets)."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    return os.environ.get(name)


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_token: str
    encryption_keys: list[str]
    timezone: str = "America/Santiago"
    daily_sync_hour: int = 6
    daily_sync_minute: int = 15
    # Si la última sincronización exitosa es más reciente que esto, abrir Actual no re-sincroniza.
    freshness_hours: int = 12
    overlap_days: int = 10
    initial_history_days: int = 90
    max_history_days: int = 365
    enabled_connectors: list[str] = field(default_factory=lambda: ["sandbox", "banco_chile", "itau", "ripley", "banco_estado"])
    notify_webhook_url: str | None = None
    actual_runner_url: str | None = None
    log_level: str = "INFO"


def _require(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(f"Falta la variable de entorno obligatoria {name} (o {name}_FILE)")
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    keys = _read_secret("AVIA_ENCRYPTION_KEYS") or ""
    token = _read_secret("AVIA_API_TOKEN") or ""
    if len(token) < 32:
        raise RuntimeError("AVIA_API_TOKEN debe tener al menos 32 caracteres")
    key_list = [k.strip() for k in keys.split(",") if k.strip()]
    if not key_list:
        raise RuntimeError("AVIA_ENCRYPTION_KEYS es obligatoria (lista de llaves Fernet, la primera es la activa)")
    return Settings(
        database_url=_require(_read_secret("AVIA_DATABASE_URL"), "AVIA_DATABASE_URL"),
        api_token=token,
        encryption_keys=key_list,
        timezone=_env("TZ", "America/Santiago") or "America/Santiago",
        daily_sync_hour=int(_env("AVIA_DAILY_SYNC_HOUR", "6") or 6),
        daily_sync_minute=int(_env("AVIA_DAILY_SYNC_MINUTE", "15") or 15),
        freshness_hours=int(_env("AVIA_FRESHNESS_HOURS", "12") or 12),
        overlap_days=int(_env("AVIA_OVERLAP_DAYS", "10") or 10),
        initial_history_days=int(_env("AVIA_INITIAL_HISTORY_DAYS", "90") or 90),
        max_history_days=int(_env("AVIA_MAX_HISTORY_DAYS", "365") or 365),
        enabled_connectors=[
            c.strip() for c in (_env("AVIA_ENABLED_CONNECTORS", "sandbox,banco_chile,itau,ripley,banco_estado") or "").split(",") if c.strip()
        ],
        notify_webhook_url=_env("AVIA_NOTIFY_WEBHOOK_URL"),
        actual_runner_url=_env("AVIA_ACTUAL_RUNNER_URL"),
        log_level=_env("AVIA_LOG_LEVEL", "INFO") or "INFO",
    )
