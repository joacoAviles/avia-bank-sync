"""API HTTP de AVIA Bank Sync. Consumida por el sync-server de Actual (app-avia).

Autenticación: Bearer token compartido (AVIA_API_TOKEN). La API solo debe
exponerse en la red Docker interna; nunca publicar este puerto a Internet.
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .. import db
from ..config import get_settings
from ..crypto import SecretBox
from ..engine.sync import SyncEngine, SyncInProgress, recover_interrupted_runs
from ..logging_setup import setup_logging
from ..scheduler import AviaScheduler
from ..service import AviaService, ServiceError
from . import panel

log = logging.getLogger("avia.api")


class State:
    """Estado global del proceso: el servicio y el scheduler diario."""
    service: AviaService
    scheduler: AviaScheduler | None = None


state = State()


def build_service(settings) -> AviaService:
    """Arma AviaService con su motor de sincronización y la caja de cifrado."""
    engine = SyncEngine(settings, SecretBox(settings.encryption_keys))
    return AviaService(settings, engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque/cierre: logs, migraciones, pool, recuperar ejecuciones cortadas y scheduler."""
    settings = get_settings()
    setup_logging(settings.log_level)
    db.migrate(settings.database_url)
    db.init_pool(settings.database_url)
    n = recover_interrupted_runs()
    if n:
        log.warning("ejecuciones interrumpidas recuperadas", extra={"count": n})
    state.service = build_service(settings)
    if getattr(app.state, "enable_scheduler", True):
        state.scheduler = AviaScheduler(settings, state.service)
        state.scheduler.start()
        state.service.next_run_provider = state.scheduler.next_run_time
    yield
    if state.scheduler:
        state.scheduler.shutdown()
    db.close_pool()


app = FastAPI(title="AVIA Bank Sync", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)


def require_token(authorization: str = Header(default="")) -> None:
    """Exige `Authorization: Bearer <AVIA_API_TOKEN>` (comparación en tiempo constante)."""
    expected = get_settings().api_token
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail={"error_code": "UNAUTHORIZED", "reason": "Token inválido"})


@app.exception_handler(ServiceError)
async def service_error_handler(_req: Request, exc: ServiceError):
    # ITEM_ERROR/ITEM_LOGIN_REQUIRED es el par que Actual traduce a "requiere reautorización"
    """Convierte ServiceError al formato de error que entiende Actual."""
    etype = "ITEM_ERROR" if exc.code == "ITEM_LOGIN_REQUIRED" else "AVIA"
    return JSONResponse(status_code=exc.status,
                        content={"error_type": etype, "error_code": exc.code, "reason": exc.message})


@app.exception_handler(SyncInProgress)
async def in_progress_handler(_req: Request, exc: SyncInProgress):
    """Responde 409 SYNC_IN_PROGRESS si ya hay una sincronización corriendo."""
    return JSONResponse(status_code=409, content={"error_type": "AVIA", "error_code": "SYNC_IN_PROGRESS",
                                                  "reason": str(exc)})


# ------------------------------------------------------------ salud
@app.get("/health")
def health() -> dict[str, str]:
    """Vida del proceso (sin tocar la base)."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    """Listo para servir: la base responde e indica si el scheduler corre."""
    with db.tx() as conn:
        conn.execute("SELECT 1")
    return {"status": "ready", "scheduler": bool(state.scheduler and state.scheduler.running)}


# ------------------------------------------------------- v1 (protegido)
auth = [Depends(require_token)]


class ConnectionIn(BaseModel):
    """Cuerpo para crear una conexión sin login por portal (sandbox, Mercado Pago)."""
    institution: str
    label: str | None = Field(default=None, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


class ReauthIn(BaseModel):
    """Parámetros opcionales para reautorizar una conexión."""
    params: dict[str, Any] = Field(default_factory=dict)


class TransactionsIn(BaseModel):
    """Pedido de movimientos desde Actual: cuenta AVIA, fecha inicial y cuenta de Actual."""
    accountId: str
    startDate: date
    actualAccountId: str | None = None


class LinkIn(BaseModel):
    """Cuenta de Actual a la que se vincula una cuenta bancaria."""
    actualAccountId: str


class SyncIn(BaseModel):
    """Pedido de sincronización (manual o al abrir Actual), opcionalmente solo si los datos están viejos."""
    trigger: str = "manual"
    onlyIfStale: bool = False
    connectionIds: list[str] | None = None


class LoginIn(BaseModel):
    """Inicio de login por portal: banco, RUT, clave y, si es reingreso, la conexión."""
    institution: str
    rut: str = Field(default="", max_length=20)
    password: str = Field(default="", max_length=64)
    label: str | None = Field(default=None, max_length=80)
    connectionId: str | None = None


class LoginInputIn(BaseModel):
    """Acción del usuario sobre la vista en vivo: clic, texto, tecla, scroll o cancelar."""
    type: str
    x: float | None = None
    y: float | None = None
    text: str | None = Field(default=None, max_length=200)
    key: str | None = Field(default=None, max_length=20)
    dy: float | None = None


class BalanceIn(BaseModel):
    """Saldo conciliado que informa Actual (entero ×100)."""
    clearedBalance: int  # entero x100 (formato interno de Actual)


@app.get("/v1/status", dependencies=auth)
def status():
    """Estado general: conexiones, última sincronización, próxima y pendientes de revisión."""
    return state.service.status()


@app.get("/v1/institutions", dependencies=auth)
def institutions():
    """Bancos que ofrece AVIA, si están disponibles y qué campos pide su Set up."""
    return {"institutions": state.service.institutions()}


@app.get("/v1/connections", dependencies=auth)
def connections():
    """Lista de conexiones con su estado."""
    return {"connections": state.service.status()["connections"]}


@app.post("/v1/connections", dependencies=auth, status_code=201)
def create_connection(body: ConnectionIn):
    """Crea una conexión sin login por portal (los bancos con portal usan /v1/logins)."""
    return state.service.create_connection(body.institution, body.label, body.params)


@app.delete("/v1/connections/{cid}", dependencies=auth, status_code=204)
def delete_connection(cid: str):
    """Elimina una conexión y borra su credencial cifrada."""
    state.service.delete_connection(cid)


@app.post("/v1/connections/{cid}/reauthorize", dependencies=auth)
def reauthorize(cid: str, body: ReauthIn):
    """Renueva la autorización de una conexión que el banco dejó de aceptar."""
    return state.service.reauthorize(cid, body.params)


@app.post("/v1/logins", dependencies=auth, status_code=202)
def login_start(body: LoginIn):
    """Abre el portal del banco en Chromium y empieza el ingreso con RUT y clave."""
    return state.service.login_start(body.institution, body.rut, body.password, body.label, body.connectionId)


@app.get("/v1/logins/{sid}", dependencies=auth)
def login_status(sid: str, screenshot: bool = True):
    """Estado del ingreso en curso, con captura de pantalla si espera al usuario."""
    return state.service.login_status(sid, screenshot)


@app.post("/v1/logins/{sid}/input", dependencies=auth)
def login_input(sid: str, body: LoginInputIn):
    """Reenvía al portal la acción del usuario (Mi Pass, código, CAPTCHA)."""
    return state.service.login_input(sid, body.model_dump(exclude_none=True))


@app.get("/v1/accounts", dependencies=auth)
def accounts():
    """Cuentas para «Enlazar cuenta» en Actual; la primera vez lanza la extracción y espera hasta ~50 s."""
    accs = state.service.accounts()
    st0 = state.service.status()
    sin_cuentas = any(c["status"] != "disconnected" and not c["accounts"] for c in st0["connections"])
    if (not accs or sin_cuentas) and st0["configured"]:
        # Primera vez: aún no hay cuentas guardadas. Lanzar la extracción y esperar hasta ~50 s
        # (Actual corta a los 60 s). Si no alcanza, la sincronización sigue en segundo plano
        # y al reabrir «Enlazar cuenta» ya estarán.
        import time
        log.info("accounts vacío: sincronizando por primera vez")
        state.service.start_background_sync("manual")
        for _ in range(50):
            time.sleep(1)
            if not (state.service._bg and state.service._bg.is_alive()) and not db.sync_lock_held():
                break
        accs = state.service.accounts()
    return {"accounts": accs}


@app.post("/v1/accounts/{bank_account_id}/link", dependencies=auth, status_code=204)
def link(bank_account_id: str, body: LinkIn):
    """Vincula una cuenta bancaria de AVIA con una cuenta de Actual."""
    state.service.link(bank_account_id, body.actualAccountId)


@app.post("/v1/actual-accounts/{actual_account_id}/unlink", dependencies=auth)
def unlink(actual_account_id: str):
    """Quita la vinculación de una cuenta de Actual."""
    return {"removed": state.service.unlink_actual(actual_account_id)}


@app.post("/v1/transactions", dependencies=auth)
def transactions(body: TransactionsIn):
    """Movimientos de una cuenta en el formato de bank sync de Actual."""
    return state.service.transactions_for_actual(body.accountId, body.startDate, body.actualAccountId)


@app.post("/v1/accounts/{bank_account_id}/actual-balance", dependencies=auth)
def actual_balance(bank_account_id: str, body: BalanceIn):
    """Registra el saldo de Actual y devuelve la diferencia con el banco."""
    return state.service.record_actual_balance(bank_account_id, body.clearedBalance)


@app.get("/v1/reconciliation", dependencies=auth)
def reconciliation():
    """Último saldo banco vs Actual por cuenta."""
    return {"accounts": state.service.reconciliation()}


@app.post("/v1/sync", dependencies=auth, status_code=202)
def sync(body: SyncIn):
    """Lanza una sincronización en segundo plano (manual o al abrir Actual)."""
    if body.trigger not in ("manual", "actual_open"):
        raise HTTPException(422, detail="trigger inválido")
    st = state.service.status()
    if body.onlyIfStale and not st["isStale"]:
        return {"started": False, "reason": "fresh", "lastSuccessfulSync": st["lastSuccessfulSync"]}
    if not st["configured"]:
        return {"started": False, "reason": "not_configured"}
    notify = state.scheduler.after_sync if state.scheduler else None
    started = state.service.start_background_sync(body.trigger, body.connectionIds, on_done=notify)
    return {"started": started, "reason": None if started else "already_running"}


@app.get("/v1/runs", dependencies=auth)
def runs(limit: int = 20):
    """Historial de ejecuciones de sincronización."""
    return {"runs": state.service.runs(min(limit, 200))}


@app.get("/v1/events", dependencies=auth)
def events(limit: int = 100, level: str | None = None):
    """Bitácora de eventos (info/warning/error)."""
    return {"events": state.service.events(min(limit, 500), level)}


@app.get("/v1/review", dependencies=auth)
def review():
    """Movimientos marcados para revisión manual."""
    return {"items": state.service.review_items()}


# Panel técnico (solo diagnóstico; no se necesita para operar). El HTML no tiene datos:
# los pide al API con el token que el administrador ingresa.
@app.get("/panel", response_class=HTMLResponse, include_in_schema=False)
def admin_panel():
    """Panel técnico HTML (solo por loopback del servidor)."""
    return panel.HTML
