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
    service: AviaService
    scheduler: AviaScheduler | None = None


state = State()


def build_service(settings) -> AviaService:
    engine = SyncEngine(settings, SecretBox(settings.encryption_keys))
    return AviaService(settings, engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    expected = get_settings().api_token
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail={"error_code": "UNAUTHORIZED", "reason": "Token inválido"})


@app.exception_handler(ServiceError)
async def service_error_handler(_req: Request, exc: ServiceError):
    # ITEM_ERROR/ITEM_LOGIN_REQUIRED es el par que Actual traduce a "requiere reautorización"
    etype = "ITEM_ERROR" if exc.code == "ITEM_LOGIN_REQUIRED" else "AVIA"
    return JSONResponse(status_code=exc.status,
                        content={"error_type": etype, "error_code": exc.code, "reason": exc.message})


@app.exception_handler(SyncInProgress)
async def in_progress_handler(_req: Request, exc: SyncInProgress):
    return JSONResponse(status_code=409, content={"error_type": "AVIA", "error_code": "SYNC_IN_PROGRESS",
                                                  "reason": str(exc)})


# ------------------------------------------------------------ salud
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    with db.tx() as conn:
        conn.execute("SELECT 1")
    return {"status": "ready", "scheduler": bool(state.scheduler and state.scheduler.running)}


# ------------------------------------------------------- v1 (protegido)
auth = [Depends(require_token)]


class ConnectionIn(BaseModel):
    institution: str
    label: str | None = Field(default=None, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


class ReauthIn(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class TransactionsIn(BaseModel):
    accountId: str
    startDate: date
    actualAccountId: str | None = None


class LinkIn(BaseModel):
    actualAccountId: str


class SyncIn(BaseModel):
    trigger: str = "manual"
    onlyIfStale: bool = False
    connectionIds: list[str] | None = None


class LoginIn(BaseModel):
    institution: str
    rut: str = Field(default="", max_length=20)
    password: str = Field(default="", max_length=64)
    label: str | None = Field(default=None, max_length=80)
    connectionId: str | None = None


class LoginInputIn(BaseModel):
    type: str
    x: float | None = None
    y: float | None = None
    text: str | None = Field(default=None, max_length=200)
    key: str | None = Field(default=None, max_length=20)
    dy: float | None = None


class BalanceIn(BaseModel):
    clearedBalance: int  # entero x100 (formato interno de Actual)


@app.get("/v1/status", dependencies=auth)
def status():
    return state.service.status()


@app.get("/v1/institutions", dependencies=auth)
def institutions():
    return {"institutions": state.service.institutions()}


@app.get("/v1/connections", dependencies=auth)
def connections():
    return {"connections": state.service.status()["connections"]}


@app.post("/v1/connections", dependencies=auth, status_code=201)
def create_connection(body: ConnectionIn):
    return state.service.create_connection(body.institution, body.label, body.params)


@app.delete("/v1/connections/{cid}", dependencies=auth, status_code=204)
def delete_connection(cid: str):
    state.service.delete_connection(cid)


@app.post("/v1/connections/{cid}/reauthorize", dependencies=auth)
def reauthorize(cid: str, body: ReauthIn):
    return state.service.reauthorize(cid, body.params)


@app.post("/v1/logins", dependencies=auth, status_code=202)
def login_start(body: LoginIn):
    return state.service.login_start(body.institution, body.rut, body.password, body.label, body.connectionId)


@app.get("/v1/logins/{sid}", dependencies=auth)
def login_status(sid: str, screenshot: bool = True):
    return state.service.login_status(sid, screenshot)


@app.post("/v1/logins/{sid}/input", dependencies=auth)
def login_input(sid: str, body: LoginInputIn):
    return state.service.login_input(sid, body.model_dump(exclude_none=True))


@app.get("/v1/accounts", dependencies=auth)
def accounts():
    return {"accounts": state.service.accounts()}


@app.post("/v1/accounts/{bank_account_id}/link", dependencies=auth, status_code=204)
def link(bank_account_id: str, body: LinkIn):
    state.service.link(bank_account_id, body.actualAccountId)


@app.post("/v1/actual-accounts/{actual_account_id}/unlink", dependencies=auth)
def unlink(actual_account_id: str):
    return {"removed": state.service.unlink_actual(actual_account_id)}


@app.post("/v1/transactions", dependencies=auth)
def transactions(body: TransactionsIn):
    return state.service.transactions_for_actual(body.accountId, body.startDate, body.actualAccountId)


@app.post("/v1/accounts/{bank_account_id}/actual-balance", dependencies=auth)
def actual_balance(bank_account_id: str, body: BalanceIn):
    return state.service.record_actual_balance(bank_account_id, body.clearedBalance)


@app.get("/v1/reconciliation", dependencies=auth)
def reconciliation():
    return {"accounts": state.service.reconciliation()}


@app.post("/v1/sync", dependencies=auth, status_code=202)
def sync(body: SyncIn):
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
    return {"runs": state.service.runs(min(limit, 200))}


@app.get("/v1/events", dependencies=auth)
def events(limit: int = 100, level: str | None = None):
    return {"events": state.service.events(min(limit, 500), level)}


@app.get("/v1/review", dependencies=auth)
def review():
    return {"items": state.service.review_items()}


# Panel técnico (solo diagnóstico; no se necesita para operar). El HTML no tiene datos:
# los pide al API con el token que el administrador ingresa.
@app.get("/panel", response_class=HTMLResponse, include_in_schema=False)
def admin_panel():
    return panel.HTML
