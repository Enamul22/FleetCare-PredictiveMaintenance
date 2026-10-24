import json
import numpy as np
import pandas as pd
import pytest
from fleetcare.config import FAULTS, DATA
from fleetcare.detection import sustained, classify, Baseline, rolling_features
from fleetcare.ingestion import Sources


@pytest.mark.parametrize("minutes", [5, 10, 15])
def test_elapsed_window_and_single_sample(minutes):
    t = pd.date_range("2025-01-01", periods=minutes // 5 + 1, freq="5min", tz="UTC")
    e = pd.DataFrame(dict(timestamp=t, valid=True, value=25.0))
    assert sustained(e, e.value >= 25, minutes)
    assert not sustained(e.iloc[-1:], e.value >= 25, minutes)
    assert not sustained(e.iloc[1:], e.value >= 25, minutes)


def test_missing_coverage_gap_and_ineligible():
    e = pd.DataFrame(
        dict(
            timestamp=pd.date_range("2025-01-01", periods=4, freq="5min", tz="UTC"),
            valid=[True, False, False, True],
            value=30,
        )
    )
    assert not sustained(e, e.value >= 25, 15)
    e.valid = True
    e.loc[1, "timestamp"] = e.loc[0, "timestamp"]
    assert not sustained(e, e.value >= 25, 15)
    f = Sources().telemetry("FC-01")
    f.operating_mode = "startup"
    assert classify(f, "FC-01")[0] == "unknown"
    f.operating_mode = "cruise"
    f.engine_on = False
    assert classify(f, "FC-01")[0] == "unknown"


@pytest.mark.parametrize("code", list(FAULTS))
def test_all_curated_faults(code):
    f = Sources().telemetry(code)
    assert classify(f.iloc[:14], code)[0] in ("warning", "critical")


def test_healthy_high_load_quality_and_past_only():
    for scenario in ["healthy_high_load", "sensor_quality", "missing_data"]:
        f = Sources().telemetry(scenario)
        assert all(
            classify(f.iloc[:n], c)[0] not in ("warning", "critical")
            for n in range(1, len(f) + 1)
            for c in FAULTS
        )
    f = Sources().telemetry("FC-01")
    original = rolling_features(f).iloc[:20]
    f.loc[20:, "oil_temperature_c"] = 9999
    pd.testing.assert_frame_equal(original, rolling_features(f).iloc[:20])


def test_baseline_is_persisted_and_has_no_truth_features():
    p = json.loads((DATA / "baseline.json").read_text())
    assert not {"condition", "fault", "future", "severity"} & set(p["features"])
    b = Baseline()
    f = Sources().telemetry("FC-01")
    f["hidden_fault"] = np.arange(len(f))
    pd.testing.assert_frame_equal(b.predict(f), b.predict(f.drop(columns="hidden_fault")))
