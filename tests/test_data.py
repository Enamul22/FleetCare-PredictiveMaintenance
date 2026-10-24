import hashlib
import json
import pandas as pd
import numpy as np
from fleetcare.config import DATA
from fleetcare.ingestion import Sources


def test_source_contracts_and_checksums():
    a = Sources().crm()
    assert len(a) == 1000 and a.vehicle_id.nunique() == 1000
    p = Sources().erp()
    assert len(p) == 64 and p.sku.nunique() == 64
    manifest = json.loads((DATA / "manifest.json").read_text())
    for path, expected in manifest["sha256"].items():
        assert hashlib.sha256((DATA / path).read_bytes()).hexdigest() == expected


def test_daily_monthly_and_clock_consistency():
    d = pd.read_parquet(DATA / "daily.parquet")
    m = pd.read_parquet(DATA / "monthly.parquet")
    assert len(d) == 365000 and len(m) == 12000
    d["month"] = d.date.dt.strftime("%Y-%m")
    derived = d.groupby(["vehicle_id", "month"]).distance_km.sum().to_numpy()
    assert np.allclose(derived, m.distance_km)
    for _, g in d.groupby("vehicle_id"):
        assert g.odometer_km.diff().dropna().ge(0).all()
        assert g.lifetime_engine_hours.diff().dropna().ge(0).all()
        assert np.allclose(g.lifetime_engine_hours.diff().dropna(), g.operating_hours.iloc[1:])
    w = pd.read_parquet(DATA / "replays.parquet")
    for vehicle, g in w.groupby("vehicle_id"):
        day = d[(d.vehicle_id == vehicle) & (d.date == g.timestamp.dt.floor("D").iloc[0])].iloc[0]
        assert np.isclose(day.operating_hours, len(g) / 12)
        assert np.isclose(day.distance_km, (g.vehicle_speed_kmh / 12).sum())
        assert np.isclose(day.odometer_km, g.odometer_km.iloc[-1])
        assert np.isclose(day.lifetime_engine_hours, g.lifetime_engine_hours.iloc[-1])
