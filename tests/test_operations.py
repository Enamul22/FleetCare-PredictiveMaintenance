import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fleetcare.service import Service, ConflictError
from conftest import customer_for


def payload(**changes):
    result = dict(
        decision="Completed",
        finding="unknown",
        confirmed_cause="unknown",
        action="report_only",
        actual_parts={},
        reported_resolution="Not resolved",
        rating=None,
        notes="partial is ordinary feedback",
        response_at="2026-10-24T12:00:00+00:00",
    )
    result.update(changes)
    return result


def create_one(s, admin):
    fault = s.faults(admin).iloc[0].to_dict()
    result = s.create_order(admin, fault["fault_id"])
    return fault, result["order_id"]


def test_detection_does_not_export_and_selected_create_is_idempotent(shared):
    s, a, path = shared
    f = s.faults(a)
    assert len(f) > 0 and f.order_id.isna().all() and f.rating.isna().all()
    assert s.db.execute("select count(*) from export_requests").fetchone()[0] == 0
    fault, oid = create_one(s, a)
    assert s.create_order(a, fault["fault_id"])["order_id"] == oid
    assert s.db.execute("select count(*) from work_orders").fetchone()[0] == 1
    joined = s.faults(a)
    assert len(joined) == len(f) and joined.fault_id.is_unique
    assert joined.response_decision.isna().all()


def test_failed_export_then_retry(shared):
    s, a, path = shared
    f = s.faults(a).iloc[0]
    failed = s.create_order(a, f.fault_id, fail_export=True)
    assert not failed["ok"] and not failed["order_id"]
    row = s.fault(a, f.fault_id)
    assert row["creation_status"] == "Failed" and row["order_id"] is None
    ok = s.create_order(a, f.fault_id)
    assert ok["ok"] and s.fault(a, f.fault_id)["creation_status"] == "Created"
    assert s.db.execute("select attempts from export_requests").fetchone()[0] == 2


def test_cross_session_authorization_and_writeback(shared):
    s, a, path = shared
    f, oid = create_one(s, a)
    customer = Service(path)
    c = customer_for(customer, f)
    other = customer.login("customer0000@fleetcare.example", "fleetcare-customer-demo")
    assert customer.orders(c).order_id.tolist() == [oid]
    assert customer.orders(other).empty
    for call in [
        lambda: customer.order(other, oid),
        lambda: customer.evidence(other, f["fault_id"], oid),
        lambda: customer.respond(other, oid, payload()),
        lambda: customer.faults(c),
        lambda: customer.fault(c, f["fault_id"]),
        lambda: customer.create_order(c, f["fault_id"]),
        lambda: customer.audit(c),
        lambda: customer.principal({"role": "admin"}),
    ]:
        with pytest.raises(PermissionError):
            call()
    customer.respond(c, oid, payload(rating=4))
    row = s.fault(a, f["fault_id"])
    assert row["order_status"] == "Completed" and row["reported_resolution"] == "Not resolved"
    assert row["fault_status"] == f["fault_status"] and row["ended_at"] == f["ended_at"]
    assert row["rating"] == 4 and row["notes"] == "partial is ordinary feedback"
    assert len(s.faults(a)) == len(__import__("pandas").read_parquet(s.data / "faults.parquet"))
    assert not customer.evidence(c, f["fault_id"], oid).empty
    customer.db.close()
    restart = Service(path)
    assert restart.order(c, oid)["response"]["rating"] == 4


def test_rejection_null_technical_fields_and_terminal_retry(shared):
    s, a, path = shared
    f, oid = create_one(s, a)
    c = customer_for(s, f)
    with pytest.raises(ValueError, match="reason"):
        s.respond(c, oid, payload(decision="Rejected"))
    assert s.order(c, oid)["status"] == "Open"
    rejected = payload(
        decision="Rejected", rejection_reason="Workshop recommendation does not apply", rating=2
    )
    rid = s.respond(c, oid, rejected)
    assert s.respond(c, oid, rejected) == rid
    row = s.fault(a, f["fault_id"])
    assert row["response_decision"] == "Rejected" and row["finding"] is None
    assert row["reported_resolution"] is None and row["actual_parts"] is None
    assert s.create_order(a, f["fault_id"])["order_id"] == oid
    with pytest.raises(ConflictError):
        s.respond(c, oid, payload())


def test_actual_parts_without_reservation_or_diagnosis(shared):
    s, a, path = shared
    f, oid = create_one(s, a)
    c = customer_for(s, f)
    order = s.order(c, oid)
    sku = order["snapshot"]["parts"][0]["sku"]
    p = payload(action="replacement", actual_parts={sku: 1}, finding="component_deterioration")
    rid = s.respond(c, oid, p)
    row = s.fault(a, f["fault_id"])
    assert json.loads(row["actual_parts"]) == {sku: 1}
    assert row["confirmed_cause"] == "unknown"
    assert s.respond(c, oid, p) == rid
    assert s.db.execute("select count(*) from work_order_responses").fetchone()[0] == 1
    with pytest.raises(ConflictError):
        s.respond(c, oid, payload(notes="changed"))


def test_validation_snapshot_and_transaction_rollback(shared, monkeypatch):
    s, a, path = shared
    f, oid = create_one(s, a)
    c = customer_for(s, f)
    for p in [
        payload(action="replacement", actual_parts={"PART-WRONG": 1}),
        payload(action="replacement", actual_parts={}),
        payload(rating=0),
        payload(rating=True),
        payload(response_at="2025-01-01"),
        payload(action="inspection", actual_parts={s.order(c, oid)["snapshot"]["parts"][0]["sku"]: 1}),
    ]:
        with pytest.raises(ValueError):
            s.respond(c, oid, p)
    assert s.order(c, oid)["status"] == "Open"
    snapshot = s.order(c, oid)["snapshot"]
    monkeypatch.setattr(s, "snapshot", lambda _: {"actions": ["Changed mapping"]})
    assert s.create_order(a, f["fault_id"])["order_id"] == oid
    assert s.order(c, oid)["snapshot"] == snapshot
    original = s.log

    def fail(*args, **kwargs):
        if args[0] == "customer_response_saved":
            raise RuntimeError("Interrupted write")
        original(*args, **kwargs)

    monkeypatch.setattr(s, "log", fail)
    with pytest.raises(RuntimeError):
        s.respond(c, oid, payload())
    assert s.order(c, oid)["status"] == "Open" and s.order(c, oid)["response"] is None


def test_concurrent_creates_and_conflicting_responses(shared):
    s, a, path = shared
    f = s.faults(a).iloc[0].to_dict()
    # Each concurrent caller owns a separate connection and validated session.
    connections = [Service(path), Service(path)]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda svc: svc.create_order(a, f["fault_id"]), connections))
    assert len({r["order_id"] for r in results}) == 1
    oid = results[0]["order_id"]
    c = customer_for(s, f)

    def respond(pair):
        svc, note = pair
        try:
            return svc.respond(c, oid, payload(notes=note))
        except ConflictError:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(respond, zip(connections, ["response one", "response two"])))
    assert results.count("conflict") == 1
    assert s.db.execute("select count(*) from work_order_responses").fetchone()[0] == 1


def test_login_session_integrity_and_logout(shared):
    s, a, path = shared
    with pytest.raises(PermissionError):
        s.login("admin@fleetcare.example", "wrong")
    with pytest.raises(PermissionError):
        s.principal("admin")
    s.logout(a)
    with pytest.raises(PermissionError):
        s.faults(a)
    for _ in range(5):
        with pytest.raises(PermissionError):
            s.login("nobody@fleetcare.example", "wrong")
    with pytest.raises(PermissionError, match="Too many"):
        s.login("nobody@fleetcare.example", "wrong")
