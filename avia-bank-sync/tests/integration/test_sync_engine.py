import threading
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from avia import db
from avia.connectors.base import BankTransaction
from avia.connectors.sandbox import SandboxConnector
from avia.engine.sync import SyncInProgress, recover_interrupted_runs
from avia.service import ServiceError
from tests.conftest import q


def connect_sandbox(service):
    return service.create_connection("sandbox", "Pruebas", {})["id"]


def test_initial_sync_imports_accounts_and_movements(service):
    connect_sandbox(service)
    accts = service.accounts()
    assert {a["type"] for a in accts} == {"checking", "credit_card"}
    assert all(a["mask"].startswith("****") for a in accts)
    n = q("SELECT count(*) AS n FROM transactions")[0]["n"]
    assert n > 50
    run = q("SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 1")[0]
    assert run["status"] == "succeeded" and run["trigger"] == "manual"


def test_rerun_is_idempotent(service):
    cid = connect_sandbox(service)
    before = q("SELECT lineage_id, status, amount FROM transactions ORDER BY lineage_id")
    res = service.engine.run("manual", [cid])
    after = q("SELECT lineage_id, status, amount FROM transactions ORDER BY lineage_id")
    assert before == after
    assert res["stats"]["new"] == 0 and res["stats"]["updated"] == 0


def test_pending_becomes_booked_without_duplicate(service, clock):
    cid = connect_sandbox(service)
    pend = q("SELECT * FROM transactions WHERE status = 'pending' ORDER BY value_date")
    assert pend, "el sandbox debe dejar pendientes recientes"
    lineages = {p["lineage_id"] for p in pend}
    total_before = q("SELECT count(*) AS n FROM transactions")[0]["n"]
    clock.d += timedelta(days=3)
    res = service.engine.run("schedule", [cid])
    assert res["stats"]["pending_booked"] >= 1
    rows = q("SELECT lineage_id, status FROM transactions WHERE lineage_id = ANY(%s)", list(lineages))
    statuses = {r["status"] for r in rows}
    assert statuses <= {"booked", "reversed"} and "booked" in statuses
    # ningún contabilizado nuevo duplicó a un pendiente promovido
    dup = q("SELECT value_date, amount, description, count(*) AS n FROM transactions WHERE status='booked'"
            " GROUP BY 1,2,3 HAVING count(*) > 1")
    assert not [d for d in dup if d["description"] not in ("NETFLIX.COM",)]
    total_after = q("SELECT count(*) AS n FROM transactions")[0]["n"]
    assert total_after >= total_before


def test_reversed_pending_is_flagged(service, clock):
    cid = connect_sandbox(service)
    # buscar un día con retención revertida en los próximos 60 días
    for _ in range(60):
        clock.d += timedelta(days=1)
        service.engine.run("schedule", [cid])
        if q("SELECT 1 FROM transactions WHERE status = 'reversed'"):
            break
    rev = q("SELECT * FROM transactions WHERE status = 'reversed'")
    assert rev and all(r["needs_review"] for r in rev)
    assert q("SELECT 1 FROM sync_events WHERE event_type = 'pending_reversed'")
    # el revertido no se exporta a Actual
    acct = rev[0]["bank_account_id"]
    out = service.transactions_for_actual(str(acct), date(2026, 1, 1), None)
    ids = {t["transactionId"] for t in out["transactions"]["all"]}
    assert rev[0]["lineage_id"] not in ids


def test_card_payment_is_paired_and_exported_as_transfer(service):
    connect_sandbox(service)
    pairs = q("SELECT * FROM transactions WHERE kind = 'card_payment' AND transfer_peer_id IS NOT NULL")
    assert pairs, "el pago del día 5 debe emparejarse"
    accts = {a["type"]: a for a in service.accounts()}
    checking, card = accts["checking"]["account_id"], accts["credit_card"]["account_id"]
    # sin vínculo de la tarjeta en Actual no hay transferencia
    out = service.transactions_for_actual(checking, date(2026, 1, 1), "actual-cc")
    assert not any("aviaTransferAccountId" in t for t in out["transactions"]["all"])
    service.transactions_for_actual(card, date(2026, 1, 1), "actual-tc")
    out = service.transactions_for_actual(checking, date(2026, 1, 1), "actual-cc")
    transfers = [t for t in out["transactions"]["all"] if t.get("aviaTransferAccountId")]
    assert transfers and all(t["aviaTransferAccountId"] == "actual-tc" for t in transfers)
    assert all(Decimal(t["transactionAmount"]["amount"]) < 0 for t in transfers)
    # el lado tarjeta nunca lleva transferencia (Actual lo concilia contra la contrapartida)
    out_card = service.transactions_for_actual(card, date(2026, 1, 1), "actual-tc")
    assert not any("aviaTransferAccountId" in t for t in out_card["transactions"]["all"])


def test_export_contract_matches_actual(service):
    connect_sandbox(service)
    acct = [a for a in service.accounts() if a["type"] == "checking"][0]
    out = service.transactions_for_actual(acct["account_id"], date(2026, 1, 1), "actual-1")
    items = out["transactions"]["all"]
    dates = [t["date"] for t in items]
    assert dates == sorted(dates, reverse=True), "Actual espera más reciente primero"
    for t in items:
        amt = t["transactionAmount"]["amount"]
        assert isinstance(amt, str) and len(amt.split(".")[1]) == 2
        assert t["transactionId"].startswith("avia:sandbox:SBX-CC-0001:")
        assert t["payeeName"]
    assert isinstance(out["startingBalance"], int)
    assert out["balances"][0]["balanceType"] == "closingBooked"
    assert len(out["transactions"]["booked"]) + len(out["transactions"]["pending"]) == len(items)
    # Saldo inicial reconstruido = contable - suma contabilizados (lo que hará el parche de loot-core)
    opening = SandboxConnector().opening_balance(SandboxConnector().get_accounts()[0])
    booked_sum = sum(Decimal(t["transactionAmount"]["amount"]) for t in out["transactions"]["booked"])
    assert Decimal(out["startingBalance"]) / 100 - booked_sum == opening


def test_mapping_is_stable_and_not_duplicated(service):
    connect_sandbox(service)
    acct = service.accounts()[0]["account_id"]
    for _ in range(3):
        service.transactions_for_actual(acct, date(2026, 3, 1), "actual-x")
    assert q("SELECT count(*) AS n FROM account_mappings")[0]["n"] == 1
    assert q("SELECT count(*) AS n FROM actual_accounts")[0]["n"] == 1
    assert service.unlink_actual("actual-x") == 1


def test_no_concurrent_runs(service):
    connect_sandbox(service)
    release = threading.Event()
    held = threading.Event()

    def hold():
        with db.sync_lock() as got:
            assert got
            held.set()
            release.wait(5)

    th = threading.Thread(target=hold)
    th.start()
    held.wait(5)
    try:
        with pytest.raises(SyncInProgress):
            service.engine.run("manual")
        assert service.status()["state"] == "syncing"
    finally:
        release.set()
        th.join()


def test_authorization_required_and_reauthorize(service, clock):
    cid = connect_sandbox(service)
    clock.d += timedelta(days=95)  # token de 90 días vence
    res = service.engine.run("schedule", [cid])
    assert res["status"] == "failed"
    assert service.status()["state"] == "authorization_required"
    assert q("SELECT count(*) AS n FROM pending_authorizations WHERE resolved_at IS NULL")[0]["n"] == 1
    acct = service.accounts()[0]["account_id"]
    with pytest.raises(ServiceError) as e:
        service.transactions_for_actual(acct, date(2026, 1, 1), None)
    assert e.value.code == "ITEM_LOGIN_REQUIRED"
    service.reauthorize(cid, {})
    assert service.status()["state"] == "synchronized"
    assert q("SELECT count(*) AS n FROM pending_authorizations WHERE resolved_at IS NULL")[0]["n"] == 0


def test_bank_error_keeps_other_data(service):
    cid = connect_sandbox(service)
    n = q("SELECT count(*) AS n FROM transactions")[0]["n"]
    with db.tx() as conn:
        service.engine.store_credentials(conn, cid, {"fail_mode": "bank_error"})
    res = service.engine.run("schedule", [cid])
    assert res["status"] == "failed"
    assert q("SELECT status FROM connections")[0]["status"] == "error"
    assert q("SELECT count(*) AS n FROM transactions")[0]["n"] == n


def test_restart_recovery_resumes_without_duplicates(service, clock):
    cid = connect_sandbox(service)
    with db.tx() as conn:
        conn.execute("INSERT INTO sync_runs (id, trigger) VALUES (%s, 'schedule')", (uuid.uuid4(),))
    assert recover_interrupted_runs() == 1
    assert q("SELECT count(*) AS n FROM sync_runs WHERE status = 'interrupted'")[0]["n"] == 1
    count = q("SELECT count(*) AS n FROM transactions")[0]["n"]
    service.engine.run("startup_recovery", [cid])
    assert q("SELECT count(*) AS n FROM transactions")[0]["n"] == count


def test_crash_mid_account_rolls_back_cursor(service, clock, monkeypatch):
    cid = connect_sandbox(service)
    cursors = q("SELECT * FROM sync_cursors ORDER BY bank_account_id")
    clock.d += timedelta(days=5)
    orig = SandboxConnector.get_transactions

    def boom(self, account, since):
        rows = orig(self, account, since)
        return rows + [BankTransaction(external_id="", status="booked", value_date=since, amount=Decimal(1),
                                       currency="CLP", description="x", booked_date=since)]

    monkeypatch.setattr(SandboxConnector, "get_transactions", boom)
    res = service.engine.run("schedule", [cid])
    assert res["stats"]["rejected"] == 2  # uno por cuenta, rechazado sin abortar
    monkeypatch.setattr(SandboxConnector, "get_transactions",
                        lambda self, a, s: (_ for _ in ()).throw(RuntimeError("caída a mitad")))
    clock.d += timedelta(days=5)
    res = service.engine.run("schedule", [cid])
    assert res["status"] == "failed"
    after = q("SELECT * FROM sync_cursors ORDER BY bank_account_id")
    assert [c["last_booked_date"] for c in after] >= [c["last_booked_date"] for c in cursors]


def test_validation_rejects_unsafe_amounts(service, monkeypatch):
    cid = connect_sandbox(service)

    def bad(self, account, since):
        return [BankTransaction(external_id="F1", status="booked", value_date=since, booked_date=since,
                                amount=1500.5, currency="CLP", description="float"),  # type: ignore[arg-type]
                BankTransaction(external_id="F2", status="booked", value_date=since, booked_date=since,
                                amount=Decimal("-10"), currency="CLP", description="USD sin TC",
                                original_amount=Decimal("-0.01"), original_currency="USD")]

    monkeypatch.setattr(SandboxConnector, "get_transactions", bad)
    res = service.engine.run("manual", [cid])
    assert res["stats"]["rejected"] == 4
    assert not q("SELECT 1 FROM transaction_identifiers WHERE value IN ('F1','F2')")


def test_ambiguous_pending_goes_to_review(service, monkeypatch, clock):
    cid = connect_sandbox(service)
    d = clock.d
    pend = [BankTransaction(external_id=f"AMB{i}", status="pending", value_date=d, amount=Decimal("-5000"),
                            currency="CLP", description="COMERCIO X") for i in range(2)]
    monkeypatch.setattr(SandboxConnector, "get_transactions", lambda self, a, s: pend if a.account_type ==
                        "checking" else [])
    service.engine.run("manual", [cid])
    booked = [BankTransaction(external_id="AMB-B", status="booked", value_date=d, booked_date=d,
                              amount=Decimal("-5000"), currency="CLP", description="COMERCIO X")]
    monkeypatch.setattr(SandboxConnector, "get_transactions", lambda self, a, s: (pend + booked) if
                        a.account_type == "checking" else [])
    res = service.engine.run("manual", [cid])
    assert res["stats"]["review"] == 1
    row = q("SELECT * FROM transactions t JOIN transaction_identifiers i ON i.transaction_id = t.id"
            " WHERE i.value = 'AMB-B'")[0]
    assert row["needs_review"]


def test_reconciliation_records_difference(service):
    connect_sandbox(service)
    acct = [a for a in service.accounts() if a["type"] == "checking"][0]
    res = service.record_actual_balance(acct["account_id"], acct["balance"])
    assert res["difference"] == 0
    res = service.record_actual_balance(acct["account_id"], acct["balance"] - 1599000)
    assert res["difference"] == Decimal("15990")
    assert q("SELECT 1 FROM sync_events WHERE event_type = 'balance_mismatch'")


def test_credentials_are_encrypted(service):
    connect_sandbox(service)
    raw = bytes(q("SELECT ciphertext FROM credentials")[0]["ciphertext"])
    assert b"token_issued" not in raw


def test_portal_institutions_use_login_flow(service):
    inst = {i["id"]: i for i in service.institutions()}
    assert inst["sandbox"]["available"] and inst["sandbox"]["testData"]
    for bank in ("banco-chile", "itau", "ripley"):
        assert inst[bank]["available"] and inst[bank]["authMethod"] == "portal_login"
        assert [f["name"] for f in inst[bank]["setupFields"]] == ["rut", "password"]
        with pytest.raises(ServiceError) as e:
            service.create_connection(bank, None, {})
        assert e.value.code == "USE_LOGIN_FLOW"


def test_delete_connection_removes_secret_keeps_history(service):
    cid = connect_sandbox(service)
    service.delete_connection(cid)
    assert not q("SELECT 1 FROM credentials")
    assert q("SELECT count(*) AS n FROM transactions")[0]["n"] > 0
    assert service.accounts() == []
    assert service.status()["state"] == "not_configured"


def test_sync_without_movements(service, monkeypatch):
    cid = connect_sandbox(service)
    monkeypatch.setattr(SandboxConnector, "get_transactions", lambda self, a, s: [])
    res = service.engine.run("manual", [cid])
    assert res["status"] == "succeeded" and res["stats"]["new"] == 0
