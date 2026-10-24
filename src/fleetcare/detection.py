"""Operational inference loads frozen healthy-development regression coefficients, never truth."""

import json
import numpy as np
import pandas as pd
from .config import DATA, FAULTS, SETTINGS
from .config import FEATURES


class Baseline:
    def __init__(self, path=None):
        self.parameters = json.loads((path or DATA / "baseline.json").read_text())
        self.version = self.parameters["version"]

    def predict(self, frame):
        x = frame[FEATURES].to_numpy(float)
        result = {}
        for sensor, p in self.parameters["sensors"].items():
            coef = np.asarray(p["coef"])
            result[sensor] = p["intercept"] + x @ coef
            if sensor in ("oil_pressure_bar", "engine_vibration_rms"):
                result[sensor] = np.maximum(0.1, result[sensor])
        return pd.DataFrame(result, index=frame.index)


def evidence(frame, code, baseline=None):
    sensor, kind, *_ = FAULTS[code]
    expected = (baseline or Baseline()).predict(frame)[sensor]
    observed = frame[sensor]
    if kind == "difference":
        value = observed - expected
    elif kind == "deficit":
        value = expected - observed
    else:
        value = observed / expected.clip(lower=0.1)
    eligible = frame.engine_on & ~frame.operating_mode.isin(["off", "startup"])
    if code == "FC-04":
        eligible &= frame.charging_expected
    if code == "FC-05":
        eligible &= frame.operating_mode.isin(["idle", "cruise", "high_load"])
        # A transition sample is not stable evidence.
        eligible &= frame.operating_mode.eq(frame.operating_mode.shift().fillna("unknown"))
    valid = eligible & frame.quality_status.eq("valid") & np.isfinite(value)
    return pd.DataFrame(
        dict(timestamp=frame.timestamp, observed=observed, expected=expected, value=value, valid=valid)
    )


def sustained(e, condition, minutes):
    """Inclusive endpoints: e.g. five minutes requires two distinct samples, not one."""
    if e.empty:
        return False
    end = e.timestamp.iloc[-1]
    start = end - pd.Timedelta(minutes=minutes)
    w = e[e.timestamp >= start].copy()
    if len(w) < 2 or w.timestamp.nunique() < 2 or not bool(w.valid.iloc[-1]):
        return False
    if (w.timestamp.iloc[-1] - w.timestamp.iloc[0]).total_seconds() < minutes * 60:
        return False
    gaps = w.timestamp.diff().dt.total_seconds().dropna() / 60
    expected = int(minutes / SETTINGS.cadence_minutes) + 1
    good = w.valid & condition.reindex(w.index).fillna(False)
    if len(w) > expected + 1 or w.timestamp.duplicated().any():
        return False
    valid_times = w.loc[w.valid, "timestamp"]
    valid_gaps = valid_times.diff().dt.total_seconds().dropna() / 60
    return bool(
        good.sum() / expected >= SETTINGS.minimum_coverage
        and gaps.max() <= SETTINGS.cadence_minutes * SETTINGS.max_gap_cadences
        and (valid_gaps.empty or valid_gaps.max() <= SETTINGS.cadence_minutes * SETTINGS.max_gap_cadences)
        and (~condition.reindex(w.index).fillna(False) & w.valid).sum() == 0
    )


def classify(frame, code, baseline=None):
    e = evidence(frame, code, baseline)
    _, kind, warn, crit, duration, recover, _ = FAULTS[code]
    low = kind == "ratio_low"
    critical = e.value.le(crit) if low else e.value.ge(crit)
    warning = e.value.le(warn) if low else e.value.ge(warn)
    recovery = e.value.gt(recover) if low else e.value.lt(recover)
    if sustained(e, critical, 5):
        return "critical", e
    if sustained(e, warning, duration):
        return "warning", e
    if sustained(e, recovery, 15):
        return "recovered", e
    return "unknown", e


def rolling_features(frame, baseline=None):
    """Past/current-only rolling medians; no centred windows or future fill."""
    out = pd.DataFrame(index=frame.index)
    for code in FAULTS:
        e = evidence(frame, code, baseline)
        out[code] = e.value.where(e.valid).rolling(4, min_periods=2).median()
    return out
