"""Login asistido contra un portal bancario FALSO servido localmente (Chrome real)."""

import os
import re
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

from avia.connectors.portal import ExtractionPending
from avia.portal import rut as rutlib
from avia.portal.banks import PortalConfig
from avia.portal.manager import LoginManager
from tests.conftest import q

# Chrome del sistema si existe (Linux/CI); si no, el Chromium de Playwright (`python -m playwright install chromium`).
for _chrome in ("/usr/bin/google-chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
    if os.path.exists(_chrome):
        os.environ.setdefault("AVIA_CHROMIUM_PATH", _chrome)
        break
VALID_RUT = "11.111.111-1"

LOGIN = """<!doctype html><html><body>
<form id=f method=post action=/login>
 <input name=userRut placeholder="Ingresa tu RUT"><input name=userPassword type=password>
 <button type=button id=ppriv_per-login-click-ingresar-login onclick="f.submit()">INGRESAR</button>
 {error}
</form></body></html>"""
MFA = """<!doctype html><html><body><h2>Ingresa el código que enviamos a tu celular</h2>
<form method=post action=/mfa><input name=code autofocus><button>Validar</button></form></body></html>"""
HOME = "<!doctype html><html><body><h1>Bienvenido</h1></body></html>"


class FakeBank(BaseHTTPRequestHandler):
    mode = "ok"
    seen = []

    def log_message(self, *a):
        pass

    def _html(self, body, code=200, headers=()):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    def _redirect(self, to, cookie=None):
        self.send_response(302)
        self.send_header("Location", to)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/login"):
            return self._html(LOGIN.format(error=""))
        if self.path.startswith("/mfa"):
            return self._html(MFA)
        if self.path.startswith("/mibancochile-web/"):
            return self._html(HOME)
        self._html("404", 404)

    def do_POST(self):
        data = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        if self.path == "/login":
            FakeBank.seen.append({k: v[0] for k, v in data.items()})
            if data.get("userPassword", [""])[0] != "clave-correcta":
                return self._html(LOGIN.format(error='<div role="alert">RUT o contraseña incorrectos</div>'))
            if FakeBank.mode == "mfa":
                return self._redirect("/mfa")
            return self._redirect("/mibancochile-web/home", "session=abc123; Path=/")
        if self.path == "/mfa":
            if data.get("code", [""])[0] == "123456":
                return self._redirect("/mibancochile-web/home", "session=mfa-ok; Path=/")
            return self._html(MFA)


@pytest.fixture(scope="module")
def fake_bank():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeBank)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def fake_config(base):
    return PortalConfig(
        bank_id="banco-chile", name="Banco de Chile (falso)", login_url=f"{base}/login",
        rut_selector='input[name="userRut"]', password_selector='input[name="userPassword"]',
        submit_selector="#ppriv_per-login-click-ingresar-login", rut_style="dotted",
        success_url=re.compile(re.escape(base) + r"/mibancochile-web/"), login_url_markers=("/login",),
    )


def wait(sess, states, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        if sess.state in states:
            return sess.state
        time.sleep(0.2)
    raise AssertionError(f"estado {sess.state}: {sess.message}")


def test_rut():
    assert rutlib.is_valid("11.111.111-1") and rutlib.is_valid("76.086.428-5")
    assert not rutlib.is_valid("11.111.111-2")
    assert rutlib.fmt("111111111", "dotted") == "11.111.111-1"
    assert rutlib.mask("11.111.111-1") == "**.***.111-1"


def test_login_success_stores_session(fake_bank):
    FakeBank.mode, FakeBank.seen = "ok", []
    got = {}
    mgr = LoginManager(portals={"banco-chile": fake_config(fake_bank)})
    sess = mgr.start("banco-chile", VALID_RUT, "clave-correcta",
                     lambda s, r: got.setdefault("r", r) and {"connectionId": "x"})
    assert wait(sess, {"succeeded", "failed"}) == "succeeded", sess.message
    assert FakeBank.seen[-1]["userRut"] == "11.111.111-1"
    cookies = {c["name"]: c["value"] for c in got["r"].storage_state["cookies"]}
    assert cookies["session"] == "abc123"
    assert sess.password == ""  # no se retiene la clave


def test_wrong_password_reports_bank_message(fake_bank):
    FakeBank.mode = "ok"
    mgr = LoginManager(portals={"banco-chile": fake_config(fake_bank)})
    sess = mgr.start("banco-chile", VALID_RUT, "mala", lambda s, r: {})
    assert wait(sess, {"failed", "succeeded"}) == "failed"
    assert sess.error_code == "BANK_REJECTED"
    assert "incorrectos" in sess.message


def test_mfa_step_is_completed_by_the_user(fake_bank):
    FakeBank.mode = "mfa"
    mgr = LoginManager(portals={"banco-chile": fake_config(fake_bank)})
    sess = mgr.start("banco-chile", VALID_RUT, "clave-correcta", lambda s, r: {"connectionId": "y"},
                     auto_interactive_after_s=1.0)
    assert wait(sess, {"needs_user", "failed"}) == "needs_user"
    for _ in range(50):
        if sess.screenshot:
            break
        time.sleep(0.1)
    snap = sess.snapshot()
    assert snap["screenshot"].startswith("data:image/jpeg;base64,")
    assert "código" in (snap["hint"] or "")
    sess.send({"type": "type", "text": "123456"})
    sess.send({"type": "key", "key": "Enter"})
    assert wait(sess, {"succeeded", "failed"}) == "succeeded"
    assert sess.result == {"connectionId": "y"}


def test_cancel(fake_bank):
    FakeBank.mode = "mfa"
    mgr = LoginManager(portals={"banco-chile": fake_config(fake_bank)})
    sess = mgr.start("banco-chile", VALID_RUT, "clave-correcta", lambda s, r: {}, auto_interactive_after_s=1.0)
    wait(sess, {"needs_user"})
    sess.cancel()
    assert wait(sess, {"cancelled"}) == "cancelled"


def test_service_flow_creates_encrypted_connection(fake_bank, service, monkeypatch):
    FakeBank.mode = "ok"
    # Banco de Chile ya lee cuentas desde su API REST real, que el portal falso no tiene.
    # Cada login exitoso dispara una lectura inmediata (síncrona en pruebas), así que se simula «lectura pendiente».
    from avia.connectors.bancochile import BancoChilePortal
    from avia.connectors.portal import ExtractionPending

    def pendiente(self):
        raise ExtractionPending("lectura pendiente (simulada)")
    monkeypatch.setattr(BancoChilePortal, "get_accounts", pendiente)
    service.logins = LoginManager(portals={"banco-chile": fake_config(fake_bank)})
    inst = {i["id"]: i for i in service.institutions()}
    assert inst["banco-chile"]["available"] and inst["banco-chile"]["authMethod"] == "portal_login"
    snap = service.login_start("banco-chile", VALID_RUT, "clave-correcta", None)
    sess = service.logins.get(snap["id"])
    assert wait(sess, {"succeeded", "failed"}) == "succeeded", sess.message
    cid = sess.result["connectionId"]
    raw = bytes(q("SELECT ciphertext FROM credentials WHERE connection_id = %s", cid)[0]["ciphertext"])
    assert b"clave-correcta" not in raw and b"abc123" not in raw
    row = q("SELECT * FROM connections WHERE id = %s", cid)[0]
    assert row["status"] == "connected" and row["label"].endswith("111-1")
    creds = service.engine.build_connector({**row, "connector": "banco_chile"}).credentials
    assert creds["rut"] == "111111111" and creds["storage_state"]["cookies"]
    res = service.engine.run("manual", [cid])  # ni la lectura tras el login ni esta marcan error
    assert res["status"] == "succeeded" and res["stats"]["pending_extraction"] == [cid]
    assert q("SELECT status FROM connections WHERE id = %s", cid)[0]["status"] == "connected"

    # Reingreso usando la clave guardada (sin volver a escribirla)
    snap2 = service.login_start("banco-chile", "", "", None, connection_id=cid)
    sess2 = service.logins.get(snap2["id"])
    assert wait(sess2, {"succeeded", "failed"}) == "succeeded"
    assert q("SELECT count(*) AS n FROM connections")[0]["n"] == 1


def test_service_validates_input(service):
    from avia.service import ServiceError
    with pytest.raises(ServiceError) as e:
        service.login_start("banco-chile", "11.111.111-2", "x", None)
    assert e.value.code == "INVALID_RUT"
    with pytest.raises(ServiceError) as e:
        service.create_connection("ripley", None, {})
    assert e.value.code == "USE_LOGIN_FLOW"
    with pytest.raises(ServiceError) as e:
        service.create_connection("itau", None, {})
    assert e.value.code == "INSTITUTION_BLOCKED"
    with pytest.raises(ServiceError) as e:
        service.login_start("sandbox", VALID_RUT, "x", None)
    assert e.value.code == "NOT_A_PORTAL"


def test_unreachable_portal_has_clear_error():
    import dataclasses
    cfg = dataclasses.replace(fake_config("http://127.0.0.1:9"), login_url="http://127.0.0.1:9/login")
    sess = LoginManager(portals={"banco-chile": cfg}).start("banco-chile", VALID_RUT, "x", lambda s, r: {})
    assert wait(sess, {"failed"}) == "failed"
    assert sess.error_code == "PORTAL_UNREACHABLE" and "Banco de Chile" in sess.message
