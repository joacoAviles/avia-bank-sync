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
    def __init__(self, portal: PortalConfig, credentials: dict[str, Any], api_marker: str, init_script: str | None = None):
        self.portal = portal
        self.creds = credentials or {}
        self.state = self.creds.get("storage_state")
        self.new_state: dict[str, Any] | None = None
        self.api_marker = api_marker
        self.init_script = init_script
        self.headers: dict[str, str] = {}
        self.log: list[tuple[str, str, int]] = []  # (método, ruta, estado) para diagnóstico
        self._pw = self._browser = self._ctx = self.page = None

    def __enter__(self) -> "PortalClient":
        from playwright.sync_api import sync_playwright

        if not self.state and not (self.creds.get("rut") and self.creds.get("password")):
            raise AuthorizationRequired("No hay credenciales guardadas: inicia sesión en Bancos chilenos.")
        self._pw = sync_playwright().start()
        o = browser_settings()
        self._browser = self._pw.chromium.launch(
            headless=o["headless"], executable_path=o["executable_path"],
            args=["--no-first-run", "--no-default-browser-check", "--disable-dev-shm-usage"])
        self._ctx = self._browser.new_context(storage_state=self.state or None, viewport=VIEWPORT, locale="es-CL",
                                              timezone_id="America/Santiago")
        if self.init_script:
            self._ctx.add_init_script(self.init_script)
        self.page = self._ctx.new_page()
        self.page.on("request", self._on_request)
        try:
            if not self._session_ok():
                self._login()
            try:
                self.page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001 - portales con llamadas constantes nunca quedan «en reposo»
                pass
            self.new_state = self._ctx.storage_state()
        except AuthorizationRequired:
            self.__exit__(None, None, None)
            raise
        except Exception as exc:  # noqa: BLE001
            where = self._where()
            self.__exit__(None, None, None)
            raise AuthorizationRequired(f"No se pudo entrar a {self.portal.name} ({type(exc).__name__}; "
                                        f"página: {where}).") from exc
        return self

    def _where(self) -> str:
        try:
            from urllib.parse import urlsplit
            u = urlsplit(self.page.url)
            return f"{u.netloc}{u.path}"[:100]
        except Exception:  # noqa: BLE001
            return "?"

    def _session_ok(self) -> bool:
        if not self.state:
            return False
        try:
            self.page.goto(self.portal.login_url, wait_until="domcontentloaded", timeout=45000)
            self.page.wait_for_url(lambda u: self.portal.is_success(u), timeout=20000)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _login(self) -> None:
        """Ingreso automático con RUT y clave guardados (como lo haría el titular)."""
        from . import rut as rutlib

        p = self.portal
        if not (self.creds.get("rut") and self.creds.get("password")):
            raise AuthorizationRequired(f"La sesión con {p.name} expiró; vuelve a iniciar sesión.")
        self.page.goto(p.login_url, wait_until="domcontentloaded", timeout=45000)
        for sel in p.pre_clicks:
            try:
                self.page.locator(sel).first.click(timeout=15000)
            except Exception:  # noqa: BLE001
                pass
        self.page.locator(p.rut_selector).first.wait_for(state="visible", timeout=30000)
        self.page.locator(p.rut_selector).first.click()
        self.page.locator(p.rut_selector).first.press_sequentially(rutlib.fmt(self.creds["rut"], p.rut_style), delay=60)
        self.page.locator(p.password_selector).first.click()
        self.page.locator(p.password_selector).first.press_sequentially(self.creds["password"], delay=60)
        self.page.wait_for_timeout(400)
        self.page.locator(p.submit_selector).first.click()
        try:
            self.page.wait_for_url(lambda u: p.is_success(u), timeout=60000)
        except Exception as exc:  # noqa: BLE001
            raise AuthorizationRequired(
                f"{p.name} no dejó entrar automáticamente (¿clave cambiada, segundo factor o verificación?). "
                f"Vuelve a iniciar sesión desde Actual. Página: {self._where()}") from exc

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
            import re as _re
            snip = _re.sub(r"\d", "9", (res["text"] or "")[:220]).replace("\n", " ")
            raise BankError(f"{self.portal.name}: HTTP {res['status']} en {path[-1]} · {snip}")
        try:
            return json.loads(res["text"]) if res["text"] else None
        except ValueError as exc:
            raise BankError(f"{self.portal.name}: respuesta no es JSON en {path[-1]}") from exc
