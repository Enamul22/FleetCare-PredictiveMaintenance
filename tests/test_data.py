import hashlib
import json
import numpy as np
import pandas as pd
from fleetcare.config import DATA
from fleetcare.temporal import supported_minutes, counters
from fleetcare.ingestion import Sources


def test_complete_source_contract_and_checksums():
    a = Sources().crm()
    assert len(a) == a.vehicle_id.nunique() == 1000
    assert a.customer_name.notna().all() and a.city.notna().all()
    assert a.groupby("customer_id").customer_name.nunique().max() == 1
    assert a.groupby("city").country.nunique().max() == 1
    assert len(Sources().erp()) == 64
    run = json.loads((DATA / "detection-run.json").read_text())
    faults = pd.read_parquet(DATA / "faults.parquet")
    assert run["processed_fleet"] == 1000 and run["complete_result"]
    assert len(run["source_partition_sha256"]) == 1000
    assert len(faults) == run["fault_episodes"] and faults.fault_id.is_unique
    assert set(faults.code) == {"FC-01", "FC-02", "FC-03", "FC-04", "FC-05"}
    manifest = json.loads((DATA / "manifest.json").read_text())
    for path, digest in manifest["sha256"].items():
        assert hashlib.sha256((DATA / path).read_bytes()).hexdigest() == digest


def test_daily_monthly_and_support_counter_consistency():
    d = pd.read_parquet(DATA / "daily.parquet")
    m = pd.read_parquet(DATA / "monthly.parquet")
    assert len(d) == 365000 and len(m) == 12000
    d["month"] = d.date.dt.strftime("%Y-%m")
    assert np.allclose(d.groupby(["vehicle_id", "month"]).distance_km.sum(), m.distance_km)
    assert np.allclose(d.groupby(["vehicle_id", "month"]).operating_hours.sum(), m.operating_hours)
    assert d.groupby("vehicle_id").odometer_km.diff().dropna().ge(0).all()
    assert d.groupby("vehicle_id").lifetime_engine_hours.diff().dropna().ge(0).all()
    for path in (DATA / "support").glob("*.parquet"):
        f = pd.read_parquet(path)
        assert f.lifetime_engine_hours.diff().dropna().ge(0).all()
        v = d[d.vehicle_id == f.vehicle_id.iloc[0]].set_index("date")
        for date, g in f.groupby(f.timestamp.dt.floor("D")):
            day = v.loc[date]
            assert np.isclose(day.operating_hours, supported_minutes(g).sum() / 60)
            assert np.isclose(day.distance_km, counters(g)[1][-1])
            assert np.isclose(day.odometer_km, g.odometer_km.iloc[-1])
            assert np.isclose(day.lifetime_engine_hours, g.lifetime_engine_hours.iloc[-1])
