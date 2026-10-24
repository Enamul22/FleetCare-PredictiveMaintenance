"""Offline complete-fleet materialization, separate from the model-evaluation cohort."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
import pandas as pd
from .config import DATA, ROOT, SETTINGS, POLICY, BASELINE
from .detection import Baseline, extract_episodes
from .temporal import supported_minutes


def materialize(source, output=DATA):
    source = Path(source)
    output = Path(output)
    manifest = json.loads((source / "manifest.json").read_text())
    if not manifest["full_detailed"]:
        raise ValueError("Operational detection requires complete detailed telemetry, not curated replays")
    files = sorted((source / "telemetry").glob("*/*.parquet"))
    if len(files) != manifest["fleet_size"]:
        raise ValueError("Incomplete fleet partitions")
    output.mkdir(parents=True, exist_ok=True)
    support = output / "support"
    support.mkdir(exist_ok=True)
    baseline = Baseline()
    faults = []
    count = 0
    hours = 0.0
    coverage = []
    hashes = {}
    for i, path in enumerate(files):
        frame = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
        episodes = extract_episodes(frame, baseline)
        count += len(frame)
        hours += supported_minutes(frame).sum() / 60
        if len(frame):
            coverage.append((frame.timestamp.min(), frame.timestamp.max()))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[str(path.relative_to(source))] = digest
        if episodes:
            name = frame.vehicle_id.iloc[0] + ".parquet"
            frame.to_parquet(support / name, index=False, compression="zstd")
            for e in episodes:
                e["support_file"] = "support/" + name
                e["run_id"] = "fleet-2025Q4-r2"
            faults.extend(episodes)
        if i % 100 == 0:
            print(f"Detected {i + 1}/{len(files)} partitions; {len(faults)} episodes", flush=True)
    columns = [
        "fault_id",
        "vehicle_id",
        "code",
        "fault_name",
        "component_id",
        "severity",
        "started_at",
        "confirmed_at",
        "ended_at",
        "recovery_confirmed_at",
        "last_detection_at",
        "fault_status",
        "sensor_verification",
        "policy_version",
        "baseline_version",
        "detection_version",
        "evidence",
        "last_observed_at",
        "support_file",
        "run_id",
    ]
    result = (
        pd.DataFrame(faults, columns=columns).sort_values(["confirmed_at", "fault_id"]).reset_index(drop=True)
    )
    if result.fault_id.duplicated().any():
        raise ValueError("Episode identities are not unique")
    result.to_parquet(output / "faults.parquet", index=False, compression="zstd")
    for name in [
        "assets.parquet",
        "parts.parquet",
        "id_map.parquet",
        "daily.parquet",
        "monthly.parquet",
        "service_history.parquet",
    ]:
        shutil.copyfile(source / name, output / name)
    run = dict(
        run_id="fleet-2025Q4-r2",
        pipeline_revision="episodes-r2",
        seed=SETTINGS.seed,
        policy_version=POLICY,
        baseline_version=BASELINE,
        processed_fleet=len(files),
        telemetry_rows=count,
        period_start="2025-10-01T00:00:00+00:00",
        period_end="2025-12-31T23:59:59+00:00",
        observed_start=min(x[0] for x in coverage).isoformat(),
        observed_end=max(x[1] for x in coverage).isoformat(),
        operating_hours=round(hours, 6),
        fault_episodes=len(result),
        generated_at=pd.Timestamp.now(tz="UTC").isoformat(),
        exposure_definition="Consecutive engine-on intervals <=10 minutes, within each vehicle; no final-sample extrapolation.",
        complete_result=True,
        source_partition_sha256=hashes,
        supporting_observations="All Q4 observations for every vehicle with a detected episode; no row cap or sampled faults.",
    )
    (output / "detection-run.json").write_text(json.dumps(run, indent=2))
    manifest.update(
        full_detailed=True,
        detailed_coverage="Full fleet processed Oct–Dec 2025; bundled support for every detected fault",
        tables={p.name: len(pd.read_parquet(p)) for p in output.glob("*.parquet")},
        sha256={
            str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.rglob("*.parquet"))
        },
    )
    manifest["sha256"]["baseline.json"] = hashlib.sha256((output / "baseline.json").read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v for k, v in run.items() if k != "source_partition_sha256"}, indent=2))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=ROOT / "data/full/update")
    p.add_argument("--output", type=Path, default=DATA)
    args = p.parse_args()
    materialize(args.source, args.output)
