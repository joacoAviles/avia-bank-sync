"""Reconocimiento de portales: SOLO LECTURA, datos enmascarados.

Uso (dentro del contenedor):  python -m avia.recon banco-chile

Reutiliza la sesión ya iniciada, recorre solo secciones de consulta (cuentas, saldos,
movimientos, tarjetas) y registra la ESTRUCTURA de lo que el portal entrega: URLs
normalizadas y forma de los JSON (claves y tipos). Los montos, nombres, RUT y números
se enmascaran. No hace transferencias, pagos ni cambios.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import parse_qs, urlsplit

from . import db
from .config import get_settings
from .crypto import SecretBox
from .portal.banks import PORTALS
from .portal.session import VIEWPORT, browser_settings

KEEP_KEY = re.compile(r"(tipo|type|moneda|currency|estado|status|producto|product|categoria|signo|clase)", re.I)
GOOD = re.compile(r"cuenta|saldo|movimiento|cartola|tarjeta|producto|posici|cupo|deuda|facturad", re.I)
BAD = re.compile(r"transfer|pagar|pago|giro|girar|elimin|cerrar|salir|logout|inscri|solicit|clave|contrat|"
                 r"aument|simul|avance|enviar|agregar|editar|bloque|desbloq|activar|anular|cambiar|modific|"
                 r"descarg|comprar|invertir|cr[eé]dito de consumo", re.I)
MAX_CLICKS = 10
MAX_ENTRIES = 60


def shape(v, key: str = "", depth: int = 0):
    if depth > 6:
        return "…"
    if isinstance(v, dict):
        return {k: shape(x, k, depth + 1) for k, x in list(v.items())[:40]}
    if isinstance(v, list):
        return {"_len": len(v), "_item": shape(v[0], key, depth + 1) if v else None}
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if v is None:
        return "null"
    if isinstance(v, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ].*)?", v) or re.fullmatch(r"\d{2}[-/]\d{2}[-/]\d{4}", v):
            return "date"
        if KEEP_KEY.search(key):
            return re.sub(r"\d", "9", v)[:30]
        return f"str({len(v)})"
    return type(v).__name__


def norm_url(u: str) -> str:
    s = urlsplit(u)
    path = re.sub(r"/\d{3,}", "/:n", s.path)
    path = re.sub(r"/[0-9a-fA-F-]{16,}", "/:id", path)
    q = sorted(parse_qs(s.query).keys())
    return f"{s.scheme}://{s.netloc}{path}" + (f"?{'&'.join(q)}" if q else "")


def mask_label(t: str) -> str:
    return re.sub(r"\d", "9", t)[:50]


def load_state(bank_id: str, full: bool = False):
    s = get_settings()
    db.init_pool(s.database_url)
    box = SecretBox(s.encryption_keys)
    with db.tx() as conn:
        row = conn.execute("SELECT c.id FROM connections c WHERE c.bank_id = %s AND c.deleted_at IS NULL "
                           "ORDER BY c.created_at DESC LIMIT 1", (bank_id,)).fetchone()
        if not row:
            sys.exit(f"No hay conexión de {bank_id}: inicia sesión primero desde Actual.")
        cred = conn.execute("SELECT ciphertext FROM credentials WHERE connection_id = %s", (row["id"],)).fetchone()
    data = box.decrypt(cred["ciphertext"])
    return data if full else data.get("storage_state")


def main(bank_id: str) -> None:
    from playwright.sync_api import sync_playwright

    portal = PORTALS[bank_id]
    state = load_state(bank_id)
    entries: dict[tuple, dict] = {}
    pages: list[dict] = []

    with sync_playwright() as pw:
        opts = browser_settings()
        br = pw.chromium.launch(headless=True, executable_path=opts["executable_path"],
                                args=["--no-first-run", "--disable-dev-shm-usage"])
        ctx = br.new_context(storage_state=state, viewport=VIEWPORT, locale="es-CL", timezone_id="America/Santiago")
        page = ctx.new_page()

        def on_response(resp):
            try:
                req = resp.request
                if req.resource_type not in ("xhr", "fetch") or len(entries) >= MAX_ENTRIES:
                    return
                if "json" not in (resp.headers.get("content-type") or ""):
                    return
                key = (req.method, norm_url(resp.url))
                if key in entries:
                    return
                body = None
                if req.post_data:
                    try:
                        body = shape(json.loads(req.post_data))
                    except Exception:  # noqa: BLE001
                        body = "(no JSON)"
                entries[key] = {"method": req.method, "url": key[1], "status": resp.status, "request_body": body,
                                "response": json.dumps(shape(resp.json()), ensure_ascii=False)[:1800]}
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)
        try:
            page.goto(portal.login_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as exc:  # noqa: BLE001
            print(f"(aviso al abrir: {type(exc).__name__})", file=sys.stderr)
        landed = norm_url(page.url)
        if portal.is_login(page.url):
            print(json.dumps({"bank": bank_id, "result": "SESSION_EXPIRED", "landed": landed}, indent=1))
            br.close()
            return

        def labels():
            raw = page.eval_on_selector_all(
                "a[href], button, [role=menuitem], [role=tab]",
                "els => els.map(e => (e.innerText || e.getAttribute('aria-label') || '').trim())")
            out = []
            for t in raw:
                t = " ".join(t.split())
                if 2 <= len(t) <= 40 and t not in out:
                    out.append(t)
            return out[:80]

        first = labels()
        pages.append({"step": "inicio", "url": landed, "labels": [mask_label(t) for t in first]})
        visited: set[str] = set()
        for _ in range(MAX_CLICKS):
            todo = [t for t in labels() if GOOD.search(t) and not BAD.search(t) and t not in visited]
            if not todo:
                break
            t = todo[0]
            visited.add(t)
            try:
                page.locator("a, button, [role=menuitem], [role=tab]").filter(has_text=t).first.click(timeout=4000)
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception as exc:  # noqa: BLE001
                pages.append({"step": f"clic «{mask_label(t)}»", "error": type(exc).__name__})
                continue
            pages.append({"step": f"clic «{mask_label(t)}»", "url": norm_url(page.url),
                          "labels": [mask_label(x) for x in labels() if GOOD.search(x)][:25]})
        br.close()

    print(json.dumps({"bank": bank_id, "landed": landed, "pages": pages, "api_calls": list(entries.values())},
                     indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "banco-chile")
