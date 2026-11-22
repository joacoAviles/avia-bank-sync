"""Configuración de login de cada portal bancario.

Selectores verificados el 2026-11-14 sobre las páginas públicas de login
(sin iniciar sesión). Si un banco cambia su portal, se ajusta solo aquí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class PortalConfig:
    """Cómo entrar al portal de un banco: URL, selectores, formato de RUT y señales de éxito."""
    bank_id: str
    name: str
    login_url: str
    rut_selector: str
    password_selector: str
    submit_selector: str
    rut_style: str  # dotted | dash | plain
    # La sesión se considera iniciada cuando la URL cumple esta condición
    success_url: re.Pattern
    # Mientras la URL esté en estos hosts/rutas, seguimos en el login
    login_url_markers: tuple[str, ...]
    error_selectors: tuple[str, ...] = ('[role="alert"]', '[class*="error"]', '[class*="alert"]')
    # Antes de llenar: clics necesarios para mostrar el formulario (si aplica)
    pre_clicks: tuple[str, ...] = ()
    notes: str = ""
    hints: dict[str, str] = field(default_factory=dict)

    def is_success(self, url: str) -> bool:
        """La URL indica sesión iniciada (y no es la de login)."""
        return bool(self.success_url.search(url)) and not self.is_login(url)

    def is_login(self, url: str) -> bool:
        """La URL es una página de login."""
        return any(m in url for m in self.login_url_markers)


PORTALS: dict[str, PortalConfig] = {
    # Auth0 (login.portales.bancochile.cl) -> redirect a portalpersonas/mibancochile-web
    "banco-chile": PortalConfig(
        bank_id="banco-chile",
        name="Banco de Chile",
        login_url="https://portalpersonas.bancochile.cl/persona/",
        rut_selector='input[name="userRut"]',
        password_selector='input[name="userPassword"]',
        submit_selector="#ppriv_per-login-click-ingresar-login",
        rut_style="dotted",
        success_url=re.compile(r"^https://portalpersonas\.bancochile\.cl/mibancochile-web/", re.I),
        login_url_markers=("login.portales.bancochile.cl", "/redirect_uri"),
        error_selectors=('[role="alert"]', ".bch-login__error", '[class*="error"]', ".bch-login__modal"),
        notes="Auth0. Puede mostrar CAPTCHA tras intentos fallidos y pedir Mi Pass.",
    ),
    # WebSphere Portal: /wps/portal (público) -> /wps/myportal (autenticado)
    "itau": PortalConfig(
        bank_id="itau",
        name="Itaú Chile",
        login_url="https://banco.itau.cl/wps/portal/newolb/web/login",
        rut_selector="#loginNameID",
        password_selector="#pswdId",
        submit_selector="#btnLoginPortal2",
        rut_style="dotted",
        success_url=re.compile(r"^https://banco\.itau\.cl/wps/myportal/", re.I),
        login_url_markers=("/wps/portal/newolb/web/login",),
        notes="reCAPTCHA v3 invisible: el banco puede rechazar el ingreso automatizado.",
    ),
    # Login en modal sobre la home pública (bancoestado.cl); campos #rut / #pass / #btnLogin
    "banco-estado": PortalConfig(
        bank_id="banco-estado",
        name="BancoEstado",
        login_url="https://www.bancoestado.cl/content/bancoestado-public/cl/es/home/home.html",
        rut_selector="#rut",
        password_selector="#pass",
        submit_selector="#btnLogin",
        rut_style="plain",  # el campo pide «12345678k», sin puntos ni guion
        pre_clicks=('a:has-text("Banca en Línea")',),
        # Autenticado = cualquier página de bancoestado.cl fuera de la home pública
        success_url=re.compile(r"^https://(?!www\.bancoestado\.cl/content/bancoestado-public/)[a-z0-9.-]*bancoestado\.cl/", re.I),
        login_url_markers=("bancoestado-public", "#/login", "login-bech"),
        notes="Campos verificados el 2026-11-15 sin iniciar sesión. URL de éxito por confirmar en el primer ingreso real.",
    ),
    # Angular 18 (web.bancoripley.cl): /onboarding -> /login -> área privada
    "ripley": PortalConfig(
        bank_id="ripley",
        name="Banco Ripley",
        login_url="https://web.bancoripley.cl/login",
        rut_selector='input[name="rut"]',
        password_selector='input[name="password"]',
        submit_selector='.login-form__actions button.primary, button:has-text("Ingresar")',
        rut_style="dotted",
        success_url=re.compile(r"^https://web\.bancoripley\.cl/(?!login|onboarding)[a-z]", re.I),
        login_url_markers=("web.bancoripley.cl/login", "web.bancoripley.cl/onboarding"),
        notes="reCAPTCHA v3 invisible: el banco puede rechazar el ingreso automatizado.",
    ),
}


def host_of(url: str) -> str:
    """Dominio de una URL."""
    return urlparse(url).netloc
