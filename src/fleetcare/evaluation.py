"""Offline immutable holdout evaluation: stable scenarios, bounded event matching and supported exposure."""

import argparse
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from .config import ROOT, FAULTS, SENSORS
from .simulation import assets, observe
from .detection import Baseline, evidence, extract_episodes, rolling_features, trace
from .temporal import supported_minutes


def wilson(k, n):
    if not n:
        return [None, None]
    p = k / n
    z = 1.96
    mid = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(mid - half, 3), round(mid + half, 3)]


def train():
    """Load frozen regression; fit only the offline challenger on healthy development observations."""
    a = assets(80, 321)
    frames = [
        observe(
            v,
            pd.date_range("2025-10-01 07:00", periods=49, freq="5min", tz="UTC"),
            100 + i,
            high_load=i % 3 == 0,
        )
        for i, v in a.iterrows()
    ]
    baseline = Baseline()
    features = pd.concat([rolling_features(g, baseline) for g in frames]).dropna()
    model = IsolationForest(n_estimators=100, contamination=0.015, random_state=431, n_jobs=1).fit(features)
    return baseline, model


def cohort(seed=20261024, start=400, count=160):
    """New reserved test partition after review fixes; never used to fit or tune policies."""
    r = np.random.default_rng(seed)
    a = assets(1000, 784)
    cases = []
    events = []
    for i in range(count):
        v = a.iloc[start + i]
        ts = pd.date_range("2025-11-20 06:00", periods=49, freq="5min", tz="UTC")
        conditions = {}
        kinds = []
        if r.random() < 0.36:
            kinds = [list(FAULTS)[int(r.integers(5))]]
            if r.random() < 0.18:
                kinds = sorted(set(kinds + [list(FAULTS)[int(r.integers(5))]]))
        for code in sorted(kinds):
            severity = float(r.uniform(0.20, 0.98))
            gradual = bool(r.random() < 0.5)
            cond = np.zeros(49)
            cond[12:37] = np.clip(np.arange(25) / 18, 0, 1) * severity if gradual else severity
            episodes = [(12, 36)]
            if i % 9 == 0:
                cond[42:] = severity
                episodes.append((42, 48))
            conditions[code] = cond
            for j, (left, right) in enumerate(episodes):
                failures = np.flatnonzero(cond[left : right + 1] >= 0.90) + left
                events.append(
                    dict(
                        event_id=f"EVAL-{seed}-{i}-{code}-{j}",
                        case=i,
                        vehicle_id=v.vehicle_id,
                        code=code,
                        onset=ts[left].isoformat(),
                        end=ts[right].isoformat(),
                        failure_onset=ts[failures[0]].isoformat() if len(failures) else None,
                        severity=severity,
                        gradual=gradual and j == 0,
                    )
                )
        f = observe(v, ts, 6000 + i, conditions, high_load=i % 4 == 0)
        bad = r.random(len(f)) < 0.025
        f.loc[bad, "quality_status"] = "missing"
        f.loc[bad, SENSORS] = np.nan
        if i % 17 == 0:
            f.loc[20, "oil_temperature_c"] += 40
        if i % 19 == 0:
            f.loc[20:24, "quality_status"] = "sensor_error"
        if i % 13 == 0:
            f.loc[8:10, "engine_on"] = False
            f.loc[8:10, "operating_mode"] = "off"
            f.loc[8:10, ["engine_rpm", "vehicle_speed_kmh", "engine_load_pct", "fuel_rate_lph"]] = 0
        if i % 23 == 0:
            f = f.drop(index=[21, 22, 23]).reset_index(drop=True)
        cases.append(f)
    return cases, events


def match_events(predictions, events, generic=False):
    """No grace past event end. One alert can credit at most one contemporaneous event."""
    matched = {}
    false = 0
    duplicates = 0
    early = 0
    late = 0
    no_event = 0
    for p in sorted(predictions, key=lambda x: (x["at"], x["case"], x["code"])):
        at = pd.Timestamp(p["at"])
        family = [e for e in events if e["case"] == p["case"] and (generic or e["code"] == p["code"])]
        current = sorted(
            [e for e in family if pd.Timestamp(e["onset"]) <= at <= pd.Timestamp(e["end"])],
            key=lambda e: (e["onset"], e["event_id"]),
        )
        available = [e for e in current if e["event_id"] not in matched]
        if available:
            matched[available[0]["event_id"]] = p
        elif current:
            duplicates += 1
        else:
            false += 1
            if any(pd.Timestamp(e["end"]) < at for e in family):
                late += 1
            elif any(at < pd.Timestamp(e["onset"]) for e in family):
                early += 1
            else:
                no_event += 1
    delays = []
    leads = []
    by = {code: dict(detected=0, total=0) for code in FAULTS}
    eligible = 0
    for e in events:
        by[e["code"]]["total"] += 1
        failure = e.get("failure_onset")
        later = failure and pd.Timestamp(failure) > pd.Timestamp(e["onset"])
        eligible += bool(later)
        if e["event_id"] in matched:
            by[e["code"]]["detected"] += 1
            at = pd.Timestamp(matched[e["event_id"]]["at"])
            delays.append((at - pd.Timestamp(e["onset"])).total_seconds() / 60)
            if later and at < pd.Timestamp(failure):
                leads.append((pd.Timestamp(failure) - at).total_seconds() / 60)
    for v in by.values():
        v["recall_95pct_wilson"] = wilson(v["detected"], v["total"])
    return dict(
        detected_events=len(matched),
        total_events=len(events),
        event_recall=len(matched) / len(events) if events else None,
        recall_95pct_wilson=wilson(len(matched), len(events)),
        by_fault=by,
        false_incidents=false,
        alerts=len(predictions),
        duplicate_alerts=duplicates,
        early_unmatched_alerts=early,
        late_unmatched_alerts=late,
        no_event_alerts=no_event,
        median_detection_delay_minutes=float(np.median(delays)) if delays else None,
        pre_failure_supported_events=eligible,
        pre_failure_warnings=len(leads),
        median_lead_minutes=float(np.median(leads)) if leads else None,
    )


def evaluate(output=ROOT / "evaluation"):
    output = Path(output)
    output.mkdir(exist_ok=True, parents=True)
    baseline, challenger = train()
    cases, truth = cohort()
    predictions = {k: [] for k in ["rules", "isolation_forest", "raw_limits"]}
    hours = 0.0
    for i, f in enumerate(cases):
        hours += supported_minutes(f).sum() / 60
        for e in extract_episodes(f, baseline):
            predictions["rules"].append(
                dict(case=i, code=e["code"], at=e["confirmed_at"], episode_id=e["fault_id"])
            )
        features = rolling_features(f, baseline)
        valid = features.notna().all(axis=1)
        for code in FAULTS:
            valid &= evidence(f, code, baseline).valid
        scores = np.zeros(len(f), dtype=bool)
        scores[valid] = challenger.predict(features.loc[valid]) == -1
        # Generic IF persistence uses the same elapsed window machinery with a boolean proxy.
        probe = f.copy()
        expected = baseline.predict(f).charging_voltage_v
        probe["charging_voltage_v"] = expected - np.where(scores, 1.2, 0.0)
        probe.loc[~valid, "quality_status"] = "missing"
        states = trace(probe, "FC-04", baseline).status
        active = False
        for j, state in enumerate(states):
            if state == "warning" and not active:
                predictions["isolation_forest"].append(
                    dict(case=i, code="unexplained", at=f.timestamp.iloc[j].isoformat())
                )
                active = True
            if bool(valid.iloc[j]) and not scores[j]:
                active = False
        for code, (sensor, kind, *_) in FAULTS.items():
            limit = {"FC-01": 115, "FC-02": 108, "FC-03": 1.7, "FC-04": 12.8, "FC-05": 2.0}[code]
            valid_code = evidence(f, code, baseline).valid.to_numpy()
            bad = (
                (f[sensor].to_numpy() < limit)
                if kind in ("ratio_low", "deficit")
                else (f[sensor].to_numpy() > limit)
            )
            active = False
            for j in range(len(f)):
                if valid_code[j] and bad[j] and not active:
                    predictions["raw_limits"].append(
                        dict(case=i, code=code, at=f.timestamp.iloc[j].isoformat())
                    )
                    active = True
                if valid_code[j] and not bad[j]:
                    active = False
    report = dict(
        version="evaluation-r2",
        public_app_version="1.0.0",
        seed=20261024,
        policy_version="policy-1.0",
        baseline_version=baseline.version,
        development_vehicles=80,
        heldout_vehicles=len(cases),
        operating_hours=round(hours, 6),
        events=len(truth),
        exposure_definition="Sum of consecutive engine-on intervals <=10 minutes; both endpoints engine on; no final sample extrapolation. Missing sensor values retain known operating context.",
        event_matching="Stable event IDs with onset/end. Alert must fall inside the same case/family episode, inclusive, with no late grace. Recurrences are independent events. First alert recalls one event; repeats are duplicate alerts, reported separately. Early/late/no-event alerts are false. A generic IF alert can recall at most one contemporaneous event and never diagnoses its family.",
        partition="Frozen healthy baseline and healthy development VEH-0001..0080. New reserved holdout VEH-0401..0560, scenario seed 20261024. Historical seed 77881 retained only as historical evidence; no reported test tuning.",
        methods={},
    )
    for name, p in predictions.items():
        m = match_events(p, truth, generic=name == "isolation_forest")
        m["false_incidents_per_100_hours"] = m["false_incidents"] / hours * 100
        m["zero_false_rate_95pct_upper_per_100_hours"] = (
            3 / hours * 100 if m["false_incidents"] == 0 else None
        )
        report["methods"][name] = m
    report["challenger_decision"] = (
        "Isolation Forest remains an offline generic challenger. No promotion or test-driven threshold tuning."
    )
    for name, value in [("report", report), ("truth", truth), ("predictions", predictions)]:
        (output / (name + ".json")).write_text(json.dumps(value, indent=2, sort_keys=True))
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=ROOT / "evaluation")
    args = p.parse_args()
    evaluate(args.output)
