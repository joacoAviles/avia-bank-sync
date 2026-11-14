from datetime import date

import pytest
from fastapi.testclient import TestClient

from avia.api import main
from avia.config import get_settings


@pytest.fixture()
def client(fresh_db, clock, service):
    main.app.state.enable_scheduler = False
    with TestClient(main.app) as c:
        main.state.service = service  # servicio con reloj de prueba
        yield c


def H():
    return {"Authorization": f"Bearer {get_settings().api_token}"}


def test_health_is_public_and_v1_requires_token(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/v1/status").status_code == 401
    assert client.get("/v1/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/v1/status", headers=H()).json()["state"] == "not_configured"


def test_full_flow_over_http(client):
    r = client.post("/v1/connections", json={"institution": "sandbox", "label": "Mi sandbox"}, headers=H())
    assert r.status_code == 201
    st = client.get("/v1/status", headers=H()).json()
    assert st["configured"] and st["state"] == "synchronized" and st["importedTransactions"] > 0
    accts = client.get("/v1/accounts", headers=H()).json()["accounts"]
    assert len(accts) == 2
    tx = client.post("/v1/transactions", headers=H(), json={
        "accountId": accts[0]["account_id"], "startDate": "2026-01-01", "actualAccountId": "a1"}).json()
    assert tx["transactions"]["all"]
    assert client.post("/v1/sync", headers=H(), json={"trigger": "manual", "onlyIfStale": True}).json() == {
        "started": False, "reason": "fresh", "lastSuccessfulSync": client.get("/v1/status", headers=H()).json()[
            "lastSuccessfulSync"]}
    assert client.get("/panel").status_code == 200


def test_portal_bank_requires_login_flow(client):
    r = client.post("/v1/connections", json={"institution": "banco-chile"}, headers=H())
    assert r.status_code == 409 and r.json()["error_code"] == "USE_LOGIN_FLOW"
    r = client.post("/v1/logins", json={"institution": "banco-chile", "rut": "1-2", "password": "x"}, headers=H())
    assert r.status_code == 422 and r.json()["error_code"] == "INVALID_RUT"
    assert client.get("/v1/logins/nope", headers=H()).status_code == 404


def test_unknown_account_404(client):
    r = client.post("/v1/transactions", headers=H(), json={"accountId": "nope", "startDate": str(date.today())})
    assert r.status_code == 404
