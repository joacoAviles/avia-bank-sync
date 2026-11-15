"""Sesión de login asistido a un portal bancario.

AVIA abre el portal en un Chromium real (sin plugins "stealth", sin falsear la
identidad del navegador), escribe RUT y clave y envía el formulario. Si el banco
pide algo que debe hacer una persona (Mi Pass, código, CAPTCHA, aceptar términos),
la sesión pasa a `needs_user`: Actual muestra la pantalla en vivo y el usuario
resuelve el paso con clics y teclado reenviados aquí. AVIA nunca resuelve ni
evade esos controles por su cuenta.

Al terminar se guarda el `storage_state` (cookies de sesión) cifrado para que
la extracción posterior reutilice la sesión sin volver a pedir Mi Pass.

Cada sesión vive en su propio hilo (la API síncrona de Playwright está ligada al
hilo que la crea); el resto de la app se comunica solo por la cola de comandos.
"""

from __future__ import annotations

import re
import base64
import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from . import rut as rutlib
from .banks import PortalConfig

log = logging.getLogger("avia.portal")

STATES = ("starting", "filling", "submitted", "needs_user", "succeeded", "failed", "cancelled", "expired")
FINAL = {"succeeded", "failed", "cancelled", "expired"}

VIEWPORT = {"width": 1280, "height": 800}
HINTS = (
    ("mi pass", "Aprueba el ingreso en la app Mi Pass de tu celular."),
    ("mipass", "Aprueba el ingreso en la app Mi Pass de tu celular."),
    ("digipass", "Ingresa el código de tu Digipass."),
    ("itaú pass", "Aprueba el ingreso en Itaú Pass."),
    ("itau pass", "Aprueba el ingreso en Itaú Pass."),
    ("captcha", "Resuelve la verificación (CAPTCHA) en la pantalla."),
    ("no soy un robot", "Resuelve la verificación (CAPTCHA) en la pantalla."),
    ("código", "Ingresa el código que te envió el banco."),
    ("codigo", "Ingresa el código que te envió el banco."),
    ("clave dinámica", "Ingresa tu clave dinámica."),
    ("segunda clave", "Ingresa tu segunda clave."),
    ("términos", "Acepta los términos en la pantalla para continuar."),
)


def browser_settings() -> dict[str, Any]:
    headless = os.environ.get("AVIA_BROWSER_HEADLESS", "true").lower() != "false"
    path = os.environ.get("AVIA_CHROMIUM_PATH") or None
    return {"headless": headless, "executable_path": path}


@dataclass
class LoginResult:
    storage_state: dict[str, Any]
    final_url: str


@dataclass
class LoginSession:
    portal: PortalConfig
    rut: str
    password: str
    on_success: Callable[["LoginSession", LoginResult], dict[str, Any]]
    login_url: str | None = None  # override (pruebas)
    timeout_s: int = 300
    auto_interactive_after_s: float = 8.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "starting"
    message: str = "Abriendo el portal del banco…"
    hint: str | None = None
    error_code: str | None = None
    result: dict[str, Any] | None = None
    screenshot: bytes | None = None
    screenshot_at: float = 0.0
    current_url: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    _cmds: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    _thread: threading.Thread | None = None

    # ------------------------------------------------------------- público
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"login-{self.portal.bank_id}", daemon=True)
        self._thread.start()

    def send(self, cmd: dict[str, Any]) -> None:
        if self.state not in FINAL:
            self._cmds.put(cmd)

    def cancel(self) -> None:
        self.send({"type": "cancel"})

    def snapshot(self, include_screenshot: bool = True) -> dict[str, Any]:
        out = {
            "id": self.id, "bank": self.portal.bank_id, "bankName": self.portal.name,
            "state": self.state, "message": self.message, "hint": self.hint,
            "errorCode": self.error_code, "result": self.result,
            "rut": rutlib.mask(self.rut), "viewport": VIEWPORT,
        }
        if include_screenshot and self.state == "needs_user" and self.screenshot:
            out["screenshot"] = "data:image/jpeg;base64," + base64.b64encode(self.screenshot).decode()
            out["screenshotAt"] = self.screenshot_at
        return out

    # ------------------------------------------------------------- interno
    def _set(self, state: str, message: str | None = None, **kw) -> None:
        self.state = state
        if message is not None:
            self.message = message
        for k, v in kw.items():
            setattr(self, k, v)
        self.updated_at = time.time()
        log.info("login", extra={"login_id": self.id, "bank": self.portal.bank_id, "state": state})

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._set("failed", "Playwright no está instalado en el servicio AVIA.", error_code="BROWSER_MISSING")
            return
        try:
            with sync_playwright() as pw:
                opts = browser_settings()
                browser = pw.chromium.launch(
                    headless=opts["headless"], executable_path=opts["executable_path"],
                    args=["--no-first-run", "--no-default-browser-check", "--disable-dev-shm-usage"],
                )
                try:
                    ctx = browser.new_context(viewport=VIEWPORT, locale="es-CL", timezone_id="America/Santiago")
                    page = ctx.new_page()
                    self._drive(page, ctx)
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001
            if self.state not in FINAL:
                log.exception("login falló")
                self._set("failed", f"Error del navegador: {type(exc).__name__}", error_code="BROWSER_ERROR")
        finally:
            self.password = ""  # no retener la clave en memoria más de lo necesario

    def _visible_error(self, page) -> str | None:
        for sel in self.portal.error_selectors:
            try:
                for el in page.locator(sel).all()[:5]:
                    if el.is_visible():
                        txt = (el.inner_text(timeout=500) or "").strip()
                        if 4 < len(txt) < 300 and not re.search(r"olvid|recuper|clave digital", txt, re.I):
                            return " ".join(txt.split())
            except Exception:  # noqa: BLE001
                continue
        return None

    def _hint(self, page) -> str | None:
        try:
            text = page.inner_text("body", timeout=1000).lower()
        except Exception:  # noqa: BLE001
            return None
        for needle, hint in HINTS:
            if needle in text:
                return hint
        return None

    def _shoot(self, page) -> None:
        try:
            self.screenshot = page.screenshot(type="jpeg", quality=60, timeout=5000)
            self.screenshot_at = time.time()
        except Exception:  # noqa: BLE001
            pass

    def _apply(self, page, cmd: dict[str, Any]) -> bool:
        t = cmd.get("type")
        if t == "cancel":
            self._set("cancelled", "Ingreso cancelado.")
            return False
        if self.state != "needs_user":
            return True
        if t == "click":
            x = max(0, min(VIEWPORT["width"], float(cmd["x"])))
            y = max(0, min(VIEWPORT["height"], float(cmd["y"])))
            page.mouse.click(x, y)
        elif t == "type":
            page.keyboard.type(str(cmd.get("text", ""))[:200], delay=40)
        elif t == "key":
            key = str(cmd.get("key", ""))
            if key in {"Enter", "Tab", "Backspace", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Space"}:
                page.keyboard.press(key)
        elif t == "scroll":
            page.mouse.wheel(0, max(-1500, min(1500, float(cmd.get("dy", 0)))))
        return True

    def _drive(self, page, ctx) -> None:
        p = self.portal
        deadline = self.created_at + self.timeout_s
        try:
            page.goto(self.login_url or p.login_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:  # noqa: BLE001
            self._set("failed", f"No se pudo abrir el portal de {p.name}: revisa la conexión a Internet del "
                                f"servidor AVIA ({type(exc).__name__}).", error_code="PORTAL_UNREACHABLE")
            return
        self.current_url = page.url
        for sel in p.pre_clicks:
            try:
                page.locator(sel).first.click(timeout=15000)
            except Exception:  # noqa: BLE001
                log.info("pre_click omitido", extra={"login_id": self.id, "selector": sel})

        self._set("filling", "Ingresando RUT y clave…")
        try:
            page.locator(p.rut_selector).first.wait_for(state="visible", timeout=30000)
        except Exception:  # noqa: BLE001
            self._set("needs_user", f"No encontré el formulario de {p.name} (¿hay una ventana emergente, como "
                                    f"«permitir ubicación»? Haz clic sobre ella en la pantalla).  Puede que el portal haya cambiado; "
                                    "puedes ingresar manualmente en la pantalla.", hint=None)
            self._shoot(page)
            return self._wait_user(page, ctx, deadline)
        page.locator(p.rut_selector).first.click()
        page.locator(p.rut_selector).first.press_sequentially(rutlib.fmt(self.rut, p.rut_style), delay=60)
        page.locator(p.password_selector).first.click()
        page.locator(p.password_selector).first.press_sequentially(self.password, delay=60)
        self.password = ""  # ya no se necesita en esta sesión
        page.wait_for_timeout(400)
        page.locator(p.submit_selector).first.click()
        self._set("submitted", "Esperando respuesta del banco…")
        self._wait_user(page, ctx, deadline)

    def _wait_user(self, page, ctx, deadline) -> None:
        p = self.portal
        submitted_at = time.time()
        last_error = None

        while True:
            # comandos del usuario
            try:
                while True:
                    if not self._apply(page, self._cmds.get_nowait()):
                        return
            except queue.Empty:
                pass

            url = page.url
            self.current_url = url
            if p.is_success(url):
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:  # noqa: BLE001
                    pass
                state = ctx.storage_state()
                self._set("succeeded", "Sesión iniciada. Guardando acceso cifrado…", hint=None)
                try:
                    self.result = self.on_success(self, LoginResult(storage_state=state, final_url=page.url))
                    self._set("succeeded", "Conectado.")
                except Exception as exc:  # noqa: BLE001
                    log.exception("no se pudo guardar la conexión")
                    self._set("failed", f"Ingreso correcto, pero no se pudo guardar: {exc}", error_code="STORE_FAILED")
                return

            if time.time() > deadline:
                self._set("expired", "Se acabó el tiempo para completar el ingreso.", error_code="TIMEOUT")
                return

            err = self._visible_error(page) if p.is_login(url) else None
            elapsed = time.time() - submitted_at
            if self.state == "submitted":
                if err and elapsed > 6:
                    hint = self._hint(page)
                    if hint and "CAPTCHA" in hint:
                        self._set("needs_user", err, hint=hint)
                    else:
                        self._set("failed", err, error_code="BANK_REJECTED")
                        return
                elif elapsed > self.auto_interactive_after_s:
                    self._set("needs_user", "El banco pide un paso adicional. Complétalo en la pantalla.",
                              hint=self._hint(page))
            elif self.state == "needs_user":
                if err and err != last_error:
                    self.message = err
                last_error = err
                h = self._hint(page)
                if h:
                    self.hint = h
                if time.time() - self.screenshot_at > 0.8:
                    self._shoot(page)
            page.wait_for_timeout(300)
