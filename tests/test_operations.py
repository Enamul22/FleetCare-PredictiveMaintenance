import hashlib
import pandas as pd
import pytest
from fleetcare.service import Service
from fleetcare.ingestion import Sources
from fleetcare.config import FAMILIES, ROOT


def open_order(s, code="FC-01"):
    s.advance(code, 15)
    o = s.table("orders").iloc[0]
    s.transition(o.id, "assigned")
    s.transition(o.id, "in_progress")
    return o.id


@pytest.mark.parametrize("code", list(FAMILIES))
def test_feedback_loop_and_restart(tmp_path, code):
    path = tmp_path / "state.sqlite"
    s = Service(path)
    oid = open_order(s, code)
    ctx = s.order_context(oid)
    model = Sources().crm().set_index("vehicle_id").loc[ctx["vehicle_id"], "model_id"]
    family = FAMILIES[code][0]
    # FC-02 uses BIR, so thermostat is available; ALD thermostat deliberately unavailable.
    sku = f"PART-{model}-{family}-01"
    if code == "FC-02":
        assert not s.reserve(oid, sku)
        s.receive_delivery("DEL-1", sku)
        s.receive_delivery("DEL-1", sku)
    assert s.reserve(oid, sku)
    assert s.reserve(oid, sku)
    before = s.table("inventory").set_index("sku").loc[sku]
    assert before.reserved == 1
    assert (
        s.feedback(
            "F1",
            oid,
            "technician",
            "component_deterioration",
            family,
            "replace",
            {sku: 1},
            "resolved",
            at="2025-12-15T09:15:00Z",
        )
        == 1
    )
    s.feedback("F1", oid, "technician", "component_deterioration", family, "replace", {sku: 1}, "resolved")
    assert s.table("incidents").iloc[0].state != "resolved"
    counters = s.replay_frame(code).lifetime_engine_hours.copy()
    s.db.close()
    s = Service(path)
    s.export()
    s.advance(code, 15)
    assert len(s.table("orders")) == 1
    assert s.table("incidents").iloc[0].state == "resolved"
    assert len(s.table("feedback")) == 1
    inventory = s.table("inventory").set_index("sku").loc[sku]
    assert inventory.consumed == 1 and inventory.reserved == 0
    pd.testing.assert_series_equal(counters, s.replay_frame(code).lifetime_engine_hours)
    assert len(s.table("components").query("code == @code")) == 2


def test_failed_repair_does_not_resolve_and_evaluation_immutable():
    p = ROOT / "evaluation/report.json"
    checksum = hashlib.sha256(p.read_bytes()).hexdigest()
    s = Service()
    oid = open_order(s)
    assert (
        s.feedback("FAIL", oid, "technician", "no_fault_found", "unknown", "inspect_only", {}, "not_resolved")
        == 0
    )
    s.advance("FC-01", 20)
    assert s.table("incidents").iloc[0].state == "active"
    assert checksum == hashlib.sha256(p.read_bytes()).hexdigest()


def test_outbox_replay_duplicate_protection(tmp_path):
    path = tmp_path / "outbox.sqlite"
    s = Service(path)
    s.advance("FC-01", 15, True)
    assert s.table("orders").empty
    assert s.table("outbox").iloc[0].state == "retry"
    s.db.close()
    s = Service(path)
    s.export()
    s.export()
    s.ingest(Sources().telemetry("FC-01").iloc[:15])
    assert len(s.table("orders")) == len(s.table("incidents")) == 1
    assert s.table("outbox").iloc[0].attempts == 2


def test_compatibility_stockout_and_state_validation():
    s = Service()
    oid = open_order(s)
    with pytest.raises(ValueError, match="Incompatible"):
        s.reserve(oid, "PART-CED-OIL-COOLER-01")
    with pytest.raises(ValueError):
        s.transition(oid, "created")
    f = Sources().telemetry("FC-02").copy()
    s.ingest(f)
    s.export()
    oid = s.table("orders").iloc[-1].id
    assert not s.reserve(oid, "PART-ALD-THERMOSTAT-01")
    assert not s.reserve(oid, "PART-ALD-THERMOSTAT-01")
    assert s.table("orders").iloc[-1].operational_status == "waiting_for_parts"
    assert s.table("lines").set_index("sku").loc["PART-ALD-THERMOSTAT-01", "unavailable"] == 1


def test_isolation_and_customer_report():
    s1, s2 = Service(), Service()
    oid = open_order(s1)
    assert s2.table("orders").empty
    s1.feedback("C1", oid, "customer", "unknown", "unknown", "report_only", {}, "unknown")
    assert s1.table("orders").iloc[0].state == "in_progress"


def test_recurrence_escalation_and_simultaneous_faults():
    s = Service()
    f = Sources().telemetry("FC-01").copy()
    s.ingest(f.iloc[:15])
    s.export()
    initial = s.table("incidents").iloc[0]
    # Make a measured warning episode followed by persistent critical evidence.
    from fleetcare.detection import Baseline

    g = f.copy()
    expected = Baseline().predict(g).oil_temperature_c
    g.timestamp += pd.Timedelta(days=1)
    g.oil_temperature_c = expected + 18
    s.ingest(g.iloc[:15])
    assert len(s.table("incidents")) == 1
    g.timestamp += pd.Timedelta(days=1)
    g.oil_temperature_c = expected
    s.ingest(g)
    assert s.table("incidents").iloc[0].state == "resolved"
    g.timestamp += pd.Timedelta(minutes=220)
    g.oil_temperature_c = expected + 35
    s.ingest(g)
    assert len(s.table("incidents")) == 2
    assert s.table("incidents").iloc[-1].recurrence_of == initial.id
    s.export()
    assert len(s.table("orders")) == 2
    multi = Service()
    multi.advance("multi_fault", 20)
    assert set(multi.table("incidents").code) == {"FC-01", "FC-04"}


def test_cancel_returns_reservations():
    s = Service()
    oid = open_order(s)
    sku = "PART-BIR-OIL-COOLER-01"
    s.reserve(oid, sku)
    s.transition(oid, "cancelled")
    inv = s.table("inventory").set_index("sku").loc[sku]
    assert inv.available == 6 and inv.reserved == 0
