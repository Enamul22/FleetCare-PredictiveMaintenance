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


def trace(frame, code, baseline=None):
    """Batch trace with one baseline pass and bounded <=15-minute array windows.

    Semantics match classify/sustained; never scan a growing history per observation.
    """
    e = evidence(frame, code, baseline).reset_index(drop=True)
    _, kind, warn, crit, duration, recover, _ = FAULTS[code]
    t = e.timestamp.astype("int64").to_numpy() / 60_000_000_000
    valid = e.valid.to_numpy(bool)
    values = e.value.to_numpy(float)
    low = kind == "ratio_low"
    masks = [
        values <= crit if low else values >= crit,
        values <= warn if low else values >= warn,
        values > recover if low else values < recover,
    ]
    result = np.full(len(e), "unknown", dtype=object)
    # All configured windows have <=4 cadence slots, so 80% coverage requires every slot.
    # On the normal 5-minute grid this is exactly an endpoint span + rolling all test.
    delta = np.diff(t)
    if (
        len(t)
        and np.all(delta >= 5)
        and np.all(np.mod(delta, 5) == 0)
        and SETTINGS.cadence_minutes == 5
        and SETTINGS.minimum_coverage == 0.8
    ):
        for name, minutes, condition in zip(["critical", "warning", "recovered"], [5, duration, 15], masks):
            slots = minutes // 5 + 1
            good = (valid & condition).astype(int)
            sums = np.cumsum(np.r_[0, good])
            ok = np.zeros(len(e), dtype=bool)
            if len(e) >= slots:
                ok[slots - 1 :] = (sums[slots:] - sums[:-slots] == slots) & (
                    t[slots - 1 :] - t[: len(t) - slots + 1] == minutes
                )
            result[(result == "unknown") & ok] = name
        e["status"] = result
        return e

    def qualifies(i, minutes, condition):
        left = int(np.searchsorted(t, t[i] - minutes, side="left"))
        count = i - left + 1
        expected = minutes // SETTINGS.cadence_minutes + 1
        if count < 2 or count > expected + 1 or not valid[i] or t[i] - t[left] < minutes:
            return False
        ts = t[left : i + 1]
        v = valid[left : i + 1]
        cond = condition[left : i + 1]
        gaps = np.diff(ts)
        vg = np.diff(ts[v])
        return bool(
            np.all(gaps > 0)
            and np.max(gaps) <= 10
            and (not len(vg) or np.max(vg) <= 10)
            and (v & cond).sum() / expected >= SETTINGS.minimum_coverage
            and not (v & ~cond).any()
        )

    for i in range(len(e)):
        for name, minutes, condition in zip(["critical", "warning", "recovered"], [5, duration, 15], masks):
            if qualifies(i, minutes, condition):
                result[i] = name
                break
    e["status"] = result
    return e


def extract_episodes(frame, baseline=None):
    """One stable row per episode; recovery requires evidence, not end of file/feedback."""
    import hashlib
    from .config import POLICY, SETTINGS

    baseline = baseline or Baseline()
    rows = []
    if frame.empty:
        return rows
    f = frame.sort_values("timestamp").reset_index(drop=True)
    vehicle = f.vehicle_id.iloc[0]
    for code in FAULTS:
        e = trace(f, code, baseline)
        sensor, kind, warn, _, duration, _, name = FAULTS[code]
        bad = (e.value.le(warn) if kind == "ratio_low" else e.value.ge(warn)).to_numpy(bool)
        current = None
        raw_start = None
        last_bad = None
        previous_time = None
        for i, row in enumerate(e.itertuples()):
            gap = previous_time is not None and (row.timestamp - previous_time).total_seconds() > 600
            previous_time = row.timestamp
            if gap:
                raw_start = None
            if row.valid and bad[i]:
                raw_start = raw_start or row.timestamp
                last_bad = row.timestamp
            elif row.valid:
                raw_start = None
            if row.status in ("warning", "critical"):
                if current is None:
                    start = raw_start or row.timestamp - pd.Timedelta(
                        minutes=5 if row.status == "critical" else duration
                    )
                    fid = (
                        "FLT-"
                        + hashlib.sha256(f"{vehicle}|{code}|{start.isoformat()}".encode()).hexdigest()[:18]
                    )
                    current = dict(
                        fault_id=fid,
                        vehicle_id=vehicle,
                        code=code,
                        fault_name=name,
                        component_id=f"{vehicle}:{code}:original",
                        severity=row.status,
                        started_at=start.isoformat(),
                        confirmed_at=row.timestamp.isoformat(),
                        ended_at=None,
                        recovery_confirmed_at=None,
                        last_detection_at=row.timestamp.isoformat(),
                        fault_status="Active",
                        sensor_verification="Not observed",
                        policy_version=POLICY,
                        baseline_version=baseline.version,
                        detection_version="episodes-r2",
                    )
                    rows.append(current)
                current["last_detection_at"] = row.timestamp.isoformat()
                if row.status == "critical":
                    current["severity"] = "critical"
                if "evidence" not in current:
                    current["evidence"] = json.dumps(
                        dict(
                            sensor=sensor,
                            timestamp=row.timestamp.isoformat(),
                            severity=row.status,
                            observed=row.observed,
                            expected=row.expected,
                            comparison=kind,
                            value=row.value,
                            threshold=FAULTS[code][3 if row.status == "critical" else 2],
                            window_minutes=5 if row.status == "critical" else duration,
                            cadence_minutes=SETTINGS.cadence_minutes,
                        )
                    )
            elif current and row.status == "recovered":
                current.update(
                    ended_at=(last_bad or row.timestamp).isoformat(),
                    recovery_confirmed_at=row.timestamp.isoformat(),
                    fault_status="Ended",
                    sensor_verification="Recovery observed",
                )
                current = None
        for r in rows:
            if r["code"] == code:
                r["last_observed_at"] = f.timestamp.iloc[-1].isoformat()
        if current and e.status.iloc[-1] == "unknown":
            current["fault_status"] = "Unknown"
    return rows
