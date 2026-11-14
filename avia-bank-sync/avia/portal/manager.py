"""Registro en memoria de las sesiones de login activas (un solo proceso)."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .banks import PORTALS, PortalConfig
from .session import FINAL, LoginResult, LoginSession

MAX_ACTIVE = 3
KEEP_FINISHED_S = 600


class LoginManager:
    def __init__(self, portals: dict[str, PortalConfig] | None = None, login_url_override: dict[str, str] | None = None):
        self.portals = portals or PORTALS
        self.login_url_override = login_url_override or {}
        self._sessions: dict[str, LoginSession] = {}
        self._lock = threading.Lock()

    def _gc(self) -> None:
        now = time.time()
        for sid in [s for s, v in self._sessions.items() if v.state in FINAL and now - v.updated_at > KEEP_FINISHED_S]:
            del self._sessions[sid]

    def start(self, bank_id: str, rut: str, password: str,
              on_success: Callable[[LoginSession, LoginResult], dict[str, Any]], **kw) -> LoginSession:
        portal = self.portals[bank_id]
        with self._lock:
            self._gc()
            active = [s for s in self._sessions.values() if s.state not in FINAL]
            for s in active:
                if s.portal.bank_id == bank_id:
                    s.cancel()  # un login a la vez por banco
            if len([s for s in active if s.portal.bank_id != bank_id]) >= MAX_ACTIVE:
                raise RuntimeError("Demasiados ingresos en curso")
            sess = LoginSession(portal=portal, rut=rut, password=password, on_success=on_success,
                                login_url=self.login_url_override.get(bank_id), **kw)
            self._sessions[sess.id] = sess
        sess.start()
        return sess

    def get(self, sid: str) -> LoginSession | None:
        return self._sessions.get(sid)
