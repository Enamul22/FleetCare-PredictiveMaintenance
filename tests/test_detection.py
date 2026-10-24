import json
import numpy as np
import pandas as pd
import pytest
from fleetcare.config import FAULTS, DATA
from fleetcare.detection import sustained, classify, Baseline, rolling_features, trace, extract_episodes


@pytest.mark.parametrize("minutes", [5, 10, 15])
def test_elapsed_window_and_single_sample(minutes):
    t = pd.date_range("2025-01-01", periods=minutes // 5 + 1, freq="5min", tz="UTC")
    e = pd.DataFrame(dict(timestamp=t, valid=True, value=25.0))
    assert sustained(e, e.value >= 25, minutes)
    assert not sustained(e.iloc[-1:], e.value >= 25, minutes)
    assert not sustained(e.iloc[1:], e.value >= 25, minutes)


def test_missing_coverage_gap_and_ineligible(curated):
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
    f = curated("FC-01")
    f.operating_mode = "startup"
    assert classify(f, "FC-01")[0] == "unknown"
    f.operating_mode = "cruise"
    f.engine_on = False
    assert classify(f, "FC-01")[0] == "unknown"


@pytest.mark.parametrize("code", list(FAULTS))
def test_all_faults_and_trusted_batch_parity(curated, code):
    f = curated(code)
    b = Baseline()
    assert classify(f.iloc[:14], code, b)[0] in ("warning", "critical")
    expected = [classify(f.iloc[: i + 1], code, b)[0] for i in range(len(f))]
    assert trace(f, code, b).status.tolist() == expected
    assert len(extract_episodes(f, b)) == 1


@pytest.mark.parametrize("kind", ["healthy_high_load", "sensor_quality", "missing_data"])
def test_healthy_quality_and_past_only(curated, kind):
    f = curated(kind)
    for code in FAULTS:
        assert not trace(f, code).status.isin(["warning", "critical"]).any()
    original = rolling_features(f).iloc[:20]
    f.loc[20:, "oil_temperature_c"] = 9999
    pd.testing.assert_frame_equal(original, rolling_features(f).iloc[:20])


def test_baseline_frozen_without_truth_features(curated):
    p = json.loads((DATA / "baseline.json").read_text())
    assert not {"condition", "fault", "future", "severity"} & set(p["features"])
    b = Baseline()
    f = curated("FC-01")
    f["hidden_fault"] = np.arange(len(f))
    pd.testing.assert_frame_equal(b.predict(f), b.predict(f.drop(columns="hidden_fault")))


def test_ended_and_recurrent_episode_times(curated):
    f = curated("FC-01")
    b = Baseline()
    f.loc[15:25, "oil_temperature_c"] = b.predict(f).oil_temperature_c.iloc[15:26]
    episodes = extract_episodes(f, b)
    assert len(episodes) == 2
    first, second = episodes
    assert first["fault_status"] == "Ended"
    assert pd.Timestamp(first["started_at"]) < pd.Timestamp(first["confirmed_at"])
    assert pd.Timestamp(first["ended_at"]) < pd.Timestamp(first["recovery_confirmed_at"])
    assert first["fault_id"] != second["fault_id"]
    assert second["fault_status"] == "Active"


def test_gapped_batch_trace_matches_incremental(curated):
    f = curated("FC-03").drop(index=[9, 10, 11]).reset_index(drop=True)
    assert trace(f, "FC-03").status.tolist() == [classify(f.iloc[: i + 1], "FC-03")[0] for i in range(len(f))]
