"""Cliente de portal: reutiliza la sesión guardada y llama a las APIs del propio portal.

Abre el portal en un Chromium sin interfaz con la sesión (storage_state) y ejecuta
`fetch` DESDE la página (mismo origen, mismas cookies), reusando las cabeceras que el
propio portal envía en sus llamadas. No evade controles de seguridad: es la misma
sesión que el titular inició.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..connectors.base import AuthorizationRequired, BankError
from .banks import PortalConfig
from .session import VIEWPORT, browser_settings

log = logging.getLogger("avia.portal.client")

_SKIP = {"cookie", "host", "content-length", "connection", "accept-encoding", "user-agent", "origin",
         "referer", "priority", "accept-language", "content-type", "accept"}

_FETCH_JS = """
async ({method, url, body, headers}) => {
  const init = {method, credentials: 'include', headers: {'Accept': 'application/json, text/plain, */*', ...headers}};
  if (body !== null) { init.body = JSON.stringify(body); init.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(url, init);
  return {status: r.status, text: await r.text()};
}
"""


class PortalClient:
    def __init__(self, portal: PortalConfig, storage_state: dict[str, Any] | None, api_marker: str):
        self.portal = portal
        self.state = storage_state
        self.api_marker = api_marker
        self.headers: dict[str, str] = {}
        self.log: list[tuple[str, str, int]] = []  # (método, ruta, estado) para diagnóstico
        self._pw = self._browser = self._ctx = self.page = None

    def __enter__(self) -> "PortalClient":
        from playwright.sync_api import sync_playwright

        if not self.state:
            raise AuthorizationRequired("No hay sesión guardada: inicia sesión en Bancos chilenos.")
        self._pw = sync_playwright().start()
        o = browser_settings()
        self._browser = self._pw.chromium.launch(
            headless=True, executable_path=o["executable_path"],
            args=["--no-first-run", "--no-default-browser-check", "--disable-dev-shm-usage"])
        self._ctx = self._browser.new_context(storage_state=self.state, viewport=VIEWPORT, locale="es-CL",
                                              timezone_id="America/Santiago")
        self.page = self._ctx.new_page()
        self.page.on("request", self._on_request)
        try:
            self.page.goto(self.portal.login_url, wait_until="domcontentloaded", timeout=45000)
            self.page.wait_for_url(lambda u: self.portal.is_success(u), timeout=30000)
            self.page.wait_for_load_state("networkidle", timeout=20000)
        except Exception as exc:  # noqa: BLE001
            self.__exit__(None, None, None)
            raise AuthorizationRequired(f"La sesión con {self.portal.name} expiró; vuelve a iniciar sesión "
                                        f"({type(exc).__name__}).") from exc
        return self

    def __exit__(self, *exc) -> None:
        for closer in (lambda: self._browser and self._browser.close(), lambda: self._pw and self._pw.stop()):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass

    def _on_request(self, req) -> None:
        if self.api_marker in req.url and req.resource_type in ("xhr", "fetch"):
            for k, v in req.headers.items():
                kl = k.lower()
                if kl not in _SKIP and not kl.startswith(("sec-", ":")):
                    self.headers[k] = v

    def call(self, method: str, url: str, body: Any = None) -> Any:
        res = self.page.evaluate(_FETCH_JS, {"method": method, "url": url, "body": body, "headers": self.headers})
        path = url.split("?")[0].rsplit("/", 2)
        self.log.append((method, "/".join(path[-2:]), res["status"]))
        if res["status"] in (401, 403):
            raise AuthorizationRequired(f"{self.portal.name} rechazó la sesión (HTTP {res['status']}).")
        if res["status"] >= 400:
            raise BankError(f"{self.portal.name}: HTTP {res['status']} en {path[-1]}")
        try:
            return json.loads(res["text"]) if res["text"] else None
        except ValueError as exc:
            raise BankError(f"{self.portal.name}: respuesta no es JSON en {path[-1]}") from exc
