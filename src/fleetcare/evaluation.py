"""Offline-only training/evaluation entrypoint. App reads report, never this cohort or truth."""

import argparse
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import IsolationForest
from .config import DATA, ROOT, BASELINE, FAULTS, POLICY
from .simulation import assets, observe
from .config import FEATURES, SENSORS
from .detection import Baseline, classify, rolling_features, sustained


def wilson(k, n):
    if not n:
        return [None, None]
    p = k / n
    z = 1.96
    mid = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(mid - half, 3), round(mid + half, 3)]


def train():
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
    f = pd.concat(frames, ignore_index=True)
    params = dict(
        version=BASELINE,
        partition="development vehicles VEH-0001..0080; seed 321/100; healthy only",
        features=FEATURES,
        sensors={},
    )
    for sensor in SENSORS:
        model = LinearRegression().fit(f[FEATURES], f[sensor])
        params["sensors"][sensor] = dict(coef=model.coef_.tolist(), intercept=float(model.intercept_))
    (DATA / "baseline.json").write_text(json.dumps(params, indent=2))
    baseline = Baseline()
    features = pd.concat([rolling_features(g, baseline) for g in frames]).dropna()
    challenger = IsolationForest(n_estimators=100, contamination=0.015, random_state=431, n_jobs=1).fit(
        features
    )
    return baseline, challenger


def cohort():
    """Independent vehicles, seed and configurations; injected events are not rule-derived labels."""
    r = np.random.default_rng(77881)
    a = assets(1000, 784)
    cases = []
    events = []
    for i in range(160):
        v = a.iloc[200 + i]
        ts = pd.date_range("2025-11-20 06:00", periods=49, freq="5min", tz="UTC")
        c = {}
        kinds = []
        if r.random() < 0.36:
            kinds = [list(FAULTS)[int(r.integers(5))]]
            if r.random() < 0.18:
                kinds = list(set(kinds + [list(FAULTS)[int(r.integers(5))]]))
        for code in kinds:
            severity = float(r.uniform(0.20, 0.98))
            gradual = bool(r.random() < 0.5)
            cond = (
                np.clip((np.arange(49) - 12) / 22, 0, 1) * severity
                if gradual
                else np.where(np.arange(49) >= 12, severity, 0)
            )
            c[code] = cond
            events.append(
                dict(
                    case=i,
                    vehicle_id=v.vehicle_id,
                    code=code,
                    onset=ts[12].isoformat(),
                    failure_onset=ts[np.flatnonzero(cond >= 0.90)[0]].isoformat()
                    if (cond >= 0.90).any()
                    else None,
                    severity=severity,
                    gradual=gradual,
                )
            )
        f = observe(v, ts, 6000 + i, c, high_load=i % 4 == 0)
        # Holdout has shifted ambient/load combinations and subtle unlabeled measurement errors.
        bad = r.random(len(f)) < 0.025
        f.loc[bad, "quality_status"] = "missing"
        f.loc[bad, SENSORS] = np.nan
        if i % 17 == 0:
            f.loc[20, "oil_temperature_c"] += 40
        if i % 19 == 0:
            f.loc[20:24, "quality_status"] = "sensor_error"
        cases.append(f)
    return cases, events


def evaluate(output=ROOT / "evaluation"):
    output = Path(output)
    output.mkdir(exist_ok=True, parents=True)
    baseline, challenger = train()
    cases, truth = cohort()
    predictions = {name: [] for name in ["rules", "isolation_forest", "raw_limits"]}
    hours = 0
    for i, f in enumerate(cases):
        hours += int(f.engine_on.sum()) / 12
        active = set()
        rawactive = set()
        features = rolling_features(f, baseline)
        scores = pd.Series(False, index=f.index)
        valid = features.notna().all(axis=1)
        scores.loc[valid] = challenger.predict(features.loc[valid]) == -1
        if_active = False
        for j in range(len(f)):
            for code in FAULTS:
                status, _ = classify(f.iloc[: j + 1], code, baseline)
                if status in ("warning", "critical") and code not in active:
                    predictions["rules"].append(dict(case=i, code=code, at=f.timestamp.iloc[j].isoformat()))
                    active.add(code)
                if status == "recovered":
                    active.discard(code)
            e = pd.DataFrame(
                dict(
                    timestamp=f.timestamp.iloc[: j + 1], valid=valid.iloc[: j + 1], value=scores.iloc[: j + 1]
                )
            )
            if sustained(e, e.value, 10) and not if_active:
                predictions["isolation_forest"].append(
                    dict(case=i, code="unexplained", at=f.timestamp.iloc[j].isoformat())
                )
                if_active = True
            if not bool(scores.iloc[j]):
                if_active = False
            for code, (sensor, kind, *_) in FAULTS.items():
                limit = {"FC-01": 115, "FC-02": 108, "FC-03": 1.7, "FC-04": 12.8, "FC-05": 2.0}[code]
                bad = (
                    f[sensor].iloc[j] < limit
                    if kind in ("ratio_low", "deficit")
                    else f[sensor].iloc[j] > limit
                )
                if bad and f.quality_status.iloc[j] == "valid" and code not in rawactive:
                    predictions["raw_limits"].append(
                        dict(case=i, code=code, at=f.timestamp.iloc[j].isoformat())
                    )
                    rawactive.add(code)
                if not bad:
                    rawactive.discard(code)
    report = dict(
        version="evaluation-1.0",
        policy_version=POLICY,
        baseline_version=BASELINE,
        seed=77881,
        development_vehicles=80,
        heldout_vehicles=160,
        operating_hours=round(hours, 3),
        events=len(truth),
        event_matching="First qualifying alert at/after injected onset within episode; exact family for rules/raw; any family for generic IF. Other alerts are false incidents. No point adjustment.",
        partition="Development VEH-0001..0080; heldout VEH-0201..0360; curated seed 44 excluded.",
        methods={},
    )
    for name, preds in predictions.items():
        matched = set()
        false = 0
        delays = []
        leads = []
        for p in preds:
            candidates = [
                (k, t)
                for k, t in enumerate(truth)
                if t["case"] == p["case"]
                and (p["code"] == t["code"] or name == "isolation_forest")
                and pd.Timestamp(p["at"]) >= pd.Timestamp(t["onset"])
            ]
            if not candidates:
                false += 1
            for k, t in candidates:
                if k not in matched:
                    delays.append((pd.Timestamp(p["at"]) - pd.Timestamp(t["onset"])).total_seconds() / 60)
                    if t["failure_onset"] and pd.Timestamp(p["at"]) < pd.Timestamp(t["failure_onset"]):
                        leads.append(
                            (pd.Timestamp(t["failure_onset"]) - pd.Timestamp(p["at"])).total_seconds() / 60
                        )
                    matched.add(k)
        by = {
            code: dict(
                detected=sum(k in matched for k, t in enumerate(truth) if t["code"] == code),
                total=sum(t["code"] == code for t in truth),
            )
            for code in FAULTS
        }
        for v in by.values():
            v["recall_95pct_wilson"] = wilson(v["detected"], v["total"])
        report["methods"][name] = dict(
            detected_events=len(matched),
            total_events=len(truth),
            event_recall=len(matched) / len(truth),
            recall_95pct_wilson=wilson(len(matched), len(truth)),
            by_fault=by,
            false_incidents=false,
            false_incidents_per_100_hours=false / hours * 100,
            alerts=len(preds),
            median_detection_delay_minutes=float(np.median(delays)) if delays else None,
            pre_failure_supported_events=sum(t["failure_onset"] is not None for t in truth),
            pre_failure_warnings=len(leads),
            median_lead_minutes=float(np.median(leads)) if leads else None,
        )
    report["challenger_decision"] = (
        "Offline comparison only; not promoted. Generic anomaly recall does not diagnose a fault; review false-incident burden alongside family-specific rules."
    )
    report["work_order_duplicate_rate"] = dict(
        duplicates=0,
        orders=0,
        status="Measured by separate transactional integration tests; no orders exported by offline evaluator.",
    )
    (output / "report.json").write_text(json.dumps(report, indent=2))
    (output / "truth.json").write_text(json.dumps(truth, indent=2))
    (output / "predictions.json").write_text(json.dumps(predictions, indent=2))
    print(
        json.dumps(
            {
                name: {k: v for k, v in result.items() if k not in ["by_fault"]}
                for name, result in report["methods"].items()
            },
            indent=2,
        )
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=ROOT / "evaluation")
    args = p.parse_args()
    evaluate(args.output)
