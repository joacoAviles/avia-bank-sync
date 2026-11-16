from datetime import date
from decimal import Decimal

import httpx
import pytest

from avia.connectors.base import AuthorizationRequired
from avia.connectors.mercadopago import MercadoPagoConnector, parse_release_csv

CSV = """DATE,SOURCE_ID,EXTERNAL_REFERENCE,RECORD_TYPE,DESCRIPTION,NET_CREDIT_AMOUNT,NET_DEBIT_AMOUNT,GROSS_AMOUNT,BALANCE_AMOUNT
2026-10-01T00:00:00.000-04:00,,,initial_available_balance,,,,,50000.00
2026-10-02T10:15:00.000-04:00,111,bip-1,release,Pago BIP QR,0.00,1000.00,1000.00,49000.00
2026-10-03T12:00:00.000-04:00,112,ref,release,Transferencia recibida,25000.00,0.00,25000.00,74000.00
2026-10-03T12:01:00.000-04:00,112,ref,release,Transferencia recibida,25000.00,0.00,25000.00,99000.00
2026-10-04T00:00:00.000-04:00,,,total,,,,,99000.00
"""


def test_parse_signs_dedupe_and_balance():
    txs, bal = parse_release_csv(CSV)
    assert [t.amount for t in txs] == [Decimal("-1000.00"), Decimal("25000.00"), Decimal("25000.00")]
    assert len({t.external_id for t in txs}) == 3
    assert bal == Decimal("99000.00")
    assert txs[0].value_date == date(2026, 10, 2)


def test_parse_identical_rows_get_distinct_ids_and_stable_across_runs():
    row = "2026-10-03T12:00:00.000-04:00,5,r,release,Pago,0,500.00,500,0\n"
    head = CSV.splitlines()[0] + "\n"
    a, _ = parse_release_csv(head + row * 2)
    b, _ = parse_release_csv(head + row * 2)
    assert a[0].external_id != a[1].external_id
    assert [t.external_id for t in a] == [t.external_id for t in b]


def test_parse_semicolon_and_decimal_comma():
    text = "DATE;SOURCE_ID;RECORD_TYPE;DESCRIPTION;NET_CREDIT_AMOUNT;NET_DEBIT_AMOUNT;BALANCE_AMOUNT\n2026-10-02T10:00:00-04:00;9;release;Pago;0;1.234,50;10,00\n"
    txs, _ = parse_release_csv(text)
    assert txs[0].amount == Decimal("-1234.50")


def _mock(handler):
    return lambda: httpx.Client(base_url="https://api.mercadopago.com", transport=httpx.MockTransport(handler), timeout=5)


def test_full_flow(monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        assert req.headers["authorization"] == "Bearer TOK"
        p = req.url.path
        if p == "/users/me":
            return httpx.Response(200, json={"id": 123456, "site_id": "MLC"})
        if p == "/v1/account/release_report/config" and req.method == "GET":
            return httpx.Response(404)
        if p == "/v1/account/release_report/config":
            return httpx.Response(201, json={})
        if p == "/v1/account/release_report" and req.method == "POST":
            return httpx.Response(202, json={})
        if p == "/v1/account/release_report/list":
            import json as _j  # noqa
            return httpx.Response(200, json=[{"file_name": "f.csv", "date_created": "2026-11-01",
                                              "begin_date": req_dates["b"], "end_date": req_dates["e"]}])
        if p == "/v1/account/release_report/f.csv":
            return httpx.Response(200, text=CSV)
        if p.endswith("/mercadopago_account/balance"):
            return httpx.Response(404)
        return httpx.Response(500)

    req_dates = {}
    orig = handler

    def wrapper(req):
        if req.url.path == "/v1/account/release_report" and req.method == "POST":
            import json
            body = json.loads(req.content)
            req_dates["b"], req_dates["e"] = body["begin_date"], body["end_date"]
        return orig(req)

    monkeypatch.setattr(MercadoPagoConnector, "client_factory", staticmethod(_mock(wrapper)))
    monkeypatch.setattr(MercadoPagoConnector, "sleep", staticmethod(lambda s: None))
    c = MercadoPagoConnector({"access_token": "TOK"})
    creds = c.authenticate()
    assert creds["user_id"] == "123456"
    accs = c.get_accounts()
    assert accs[0].external_id == "123456"
    txs = c.get_transactions(accs[0], date.today())
    assert len(txs) == 3
    bal = c.get_balances(accs)[0]
    assert bal.booked == Decimal("99000.00")


def test_rejects_other_country_and_bad_token(monkeypatch):
    monkeypatch.setattr(MercadoPagoConnector, "client_factory", staticmethod(
        _mock(lambda r: httpx.Response(200, json={"id": 1, "site_id": "MLA"}))))
    with pytest.raises(AuthorizationRequired):
        MercadoPagoConnector({"access_token": "x"}).authenticate()
    monkeypatch.setattr(MercadoPagoConnector, "client_factory", staticmethod(_mock(lambda r: httpx.Response(401))))
    with pytest.raises(AuthorizationRequired):
        MercadoPagoConnector({"access_token": "x"}).authenticate()
    with pytest.raises(AuthorizationRequired):
        MercadoPagoConnector({}).authenticate()


def test_token_from_env_is_persisted(monkeypatch):
    monkeypatch.setenv("AVIA_MP_ACCESS_TOKEN", "ENVTOK")
    monkeypatch.setattr(MercadoPagoConnector, "client_factory", staticmethod(_mock(
        lambda r: httpx.Response(200, json={"id": 7, "site_id": "MLC"}) if r.headers["authorization"] == "Bearer ENVTOK"
        else httpx.Response(401))))
    creds = MercadoPagoConnector({}).authenticate()
    assert creds["access_token"] == "ENVTOK" and creds["user_id"] == "7"
