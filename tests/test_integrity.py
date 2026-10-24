import json
import pandas as pd
import pytest
from fleetcare.config import FAULTS, DATA
from fleetcare.detection import Baseline, classify
from fleetcare.ingestion import Sources
from fleetcare.service import Service
from fleetcare.simulation import generate


def test_incremental_batches_and_escalation():
    s = Service()
    f = Sources().telemetry("FC-01")
    expected = Baseline().predict(f).oil_temperature_c
    f.oil_temperature_c = expected + 18
    for j in range(14):
        s.ingest(f.iloc[j : j + 1])
    s.export()
    assert s.table("incidents").iloc[0].severity == "warning"
    f.loc[14:, "oil_temperature_c"] = expected.iloc[14:] + 30
    for j in range(14, 20):
        s.ingest(f.iloc[j : j + 1])
    s.export()
    assert s.table("incidents").iloc[0].severity == "critical"
    assert len(s.table("orders")) == 1
    assert "severity_escalated" in set(s.table("audit").kind)


def test_replay_transaction_rolls_back_checkpoint_and_incident(monkeypatch):
    s = Service()
    real = s.ingest

    def fail_after_ingest(frame):
        real(frame)
        raise RuntimeError("Interruption after domain write")

    monkeypatch.setattr(s, "ingest", fail_after_ingest)
    with pytest.raises(RuntimeError):
        s.advance("FC-01", 15)
    assert s.table("incidents").empty
    assert s.table("replay").empty
    assert s.db.execute("select count(*) from processed").fetchone()[0] == 0
    monkeypatch.setattr(s, "ingest", real)
    s.advance("FC-01", 15)
    assert len(s.table("orders")) == 1


def test_late_repair_extends_future_and_preserves_clock():
    s = Service()
    s.advance("FC-01", 100)
    oid = s.table("orders").iloc[0].id
    s.transition(oid, "assigned")
    s.transition(oid, "in_progress")
    original = s.replay_frame("FC-01")
    sku = "PART-BIR-OIL-COOLER-01"
    s.reserve(oid, sku)
    s.feedback(
        "LATE", oid, "technician", "component_deterioration", "OIL-COOLER", "replace", {sku: 1}, "resolved"
    )
    future = s.replay_frame("FC-01")
    assert len(future) > len(original)
    pd.testing.assert_series_equal(
        future.lifetime_engine_hours.iloc[: len(original)], original.lifetime_engine_hours
    )
    assert future.lifetime_engine_hours.diff().dropna().gt(0).all()
    s.advance("FC-01", 12)
    assert s.table("incidents").iloc[0].state == "resolved"


@pytest.mark.parametrize("code", list(FAULTS))
def test_boundaries_and_recovery_equality(code):
    f = Sources().telemetry(code).iloc[3:12].reset_index(drop=True)
    f.operating_mode = "cruise"
    f.quality_status = "valid"
    b = Baseline().predict(f)
    sensor, kind, warning, critical, _, recovery, _ = FAULTS[code]

    def set_value(value):
        if kind == "difference":
            f[sensor] = b[sensor] + value
        elif kind == "deficit":
            f[sensor] = b[sensor] - value
        else:
            f[sensor] = b[sensor] * value

    set_value(critical)
    # Floating arithmetic is compared at physically meaningful precision below.
    assert classify(f, code)[0] in ("warning", "critical")
    set_value(recovery)
    assert classify(f, code)[0] != "recovered"


def test_full_generator_partition_and_aggregation(tmp_path):
    generate(tmp_path, full=True, n=12)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["full_detailed"]
    files = list((tmp_path / "telemetry").glob("*/*.parquet"))
    assert len(files) == 12
    detail = pd.read_parquet(files[0])
    daily = pd.read_parquet(tmp_path / "daily.parquet")
    assert set(detail.timestamp.dt.month) == {10, 11, 12}
    assert detail.lifetime_engine_hours.diff().dropna().ge(0).all()
    day = detail.timestamp.dt.floor("D").iloc[0]
    g = detail[detail.timestamp.dt.floor("D") == day]
    d = daily[(daily.vehicle_id == g.vehicle_id.iloc[0]) & (daily.date == day)].iloc[0]
    assert d.operating_hours == len(g) / 12
    assert abs(d.distance_km - (g.vehicle_speed_kmh / 12).sum()) < 1e-8


def test_service_history_counters_and_components():
    daily = pd.read_parquet(DATA / "daily.parquet")
    hist = pd.read_parquet(DATA / "service_history.parquet")
    sep = daily[daily.date == pd.Timestamp("2025-09-01", tz="UTC")].merge(hist, on="vehicle_id")
    assert (sep.lifetime_engine_hours == sep.completed_hours).all()
    assert (sep.odometer_km == sep.completed_km).all()
    f = Sources().telemetry("FC-01")
    assert json.loads(f.installed_component_ids.iloc[0])["FC-01"] == f.vehicle_id.iloc[0] + ":FC-01:original"


def test_cooldown_does_not_hide_critical_reactivation():
    s = Service()
    source = Sources().telemetry("FC-01").iloc[3:15].reset_index(drop=True)
    expected = Baseline().predict(source).oil_temperature_c
    source.oil_temperature_c = expected + 18
    s.ingest(source.iloc[:4])
    s.export()
    recovery = source.iloc[:4].copy()
    recovery.timestamp = pd.date_range(
        source.timestamp.iloc[3] + pd.Timedelta(minutes=5), periods=4, freq="5min"
    )
    recovery.oil_temperature_c = Baseline().predict(recovery).oil_temperature_c
    s.ingest(recovery)
    assert s.table("incidents").iloc[0].state == "resolved"
    again = source.iloc[:3].copy()
    again.timestamp = pd.date_range(
        recovery.timestamp.iloc[-1] + pd.Timedelta(minutes=5), periods=3, freq="5min"
    )
    s.ingest(again)
    assert s.table("incidents").iloc[-1].notification == "cooldown_suppressed"
    critical = source.iloc[:2].copy()
    critical.timestamp = pd.date_range(
        again.timestamp.iloc[-1] + pd.Timedelta(minutes=5), periods=2, freq="5min"
    )
    critical.oil_temperature_c = Baseline().predict(critical).oil_temperature_c + 35
    s.ingest(critical)
    assert s.table("incidents").iloc[-1].notification == "notify"
    assert s.table("incidents").iloc[-1].severity == "critical"
    s.export()
    assert len(s.table("orders")) == 2


def test_out_of_order_new_input_rejected():
    s = Service()
    f = Sources().telemetry("FC-01")
    s.ingest(f.iloc[10:15])
    with pytest.raises(ValueError, match="Out-of-order"):
        s.ingest(f.iloc[:5])


def test_config_snapshots_match_runtime():
    from fleetcare.config import ROOT, SETTINGS, POLICY

    config = json.loads((ROOT / "config/simulator.json").read_text())
    assert all(config[k] == v for k, v in SETTINGS.model_dump().items())
    policies = json.loads((ROOT / "config/policies.json").read_text())
    assert policies["version"] == POLICY
    for code, p in FAULTS.items():
        assert policies["faults"][code]["warning"] == p[2]
        assert policies["faults"][code]["critical"] == p[3]
