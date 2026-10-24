"""Seeded synthetic observations. Hidden conditions are returned separately for offline evaluation."""

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .config import DATA, MODELS, COUNTRIES, VERSION, SETTINGS, SENSORS


def assets(n=1000, seed=SETTINGS.seed):
    r = np.random.default_rng(seed)
    return pd.DataFrame(
        [
            dict(
                vehicle_id=f"VEH-{i:04d}",
                crm_asset_id=f"CRM-A-{i:04d}",
                customer_id=f"CUS-{i // 5:04d}",
                installed_component_ids=json.dumps(
                    {f"FC-0{j}": f"VEH-{i:04d}:FC-0{j}:original" for j in range(1, 6)}
                ),
                customer_email=f"fleet{i // 5}@customer.example",
                model_id=list(MODELS)[i % 4],
                country=COUNTRIES[int(r.integers(4))],
                age_years=round(float(r.uniform(1, 12)), 1),
                initial_odometer_km=int(r.integers(10000, 190000)),
                initial_engine_hours=float(r.uniform(500, 7000)),
                usage_profile=["urban", "mixed", "motorway"][i % 3],
                source="mock-crm-v1",
                simulation_version=VERSION,
            )
            for i in range(1, n + 1)
        ]
    )


def observe(vehicle, timestamps, seed, conditions=None, high_load=False):
    """Generate correlated sensors from operating context and hidden component loss of capacity.

    conditions maps fault family -> continuous capacity loss, not detector threshold labels.
    """
    r = np.random.default_rng(seed)
    n = len(timestamps)
    minute = np.arange(n) * 5
    load = np.clip(r.normal(80 if high_load else 47, 8, n), 10, 98)
    rpm = 750 + load * 24 + r.normal(0, 80, n)
    speed = np.clip(load * 1.2 + r.normal(0, 8, n), 0, 130)
    ambient = (
        9
        + 12 * np.sin(pd.DatetimeIndex(timestamps).dayofyear.to_numpy() * 2 * np.pi / 365)
        + r.normal(0, 2, n)
    )
    warm = np.exp(-minute / 9)
    offset = list(MODELS).index(vehicle["model_id"])
    f = pd.DataFrame(
        dict(
            timestamp=pd.to_datetime(timestamps, utc=True),
            vehicle_id=vehicle["vehicle_id"],
            model_id=vehicle["model_id"],
            model_index=offset,
            telemetry_asset_id="TEL-" + vehicle["vehicle_id"][-4:],
            asset_age_years=vehicle["age_years"],
            installed_component_ids=vehicle["installed_component_ids"],
            engine_rpm=rpm,
            vehicle_speed_kmh=speed,
            engine_load_pct=load,
            ambient_temperature_c=ambient,
            warmup=warm,
            engine_on=True,
            operating_mode=np.where(minute < 15, "startup", "high_load" if high_load else "cruise"),
            charging_expected=True,
            quality_status="valid",
            source="mock-telemetry-v1",
            simulation_version=VERSION,
        )
    )
    # Heat balance, flow resistance, electrical regulation and oscillation amplitude; independent of policy.
    oil = 78 + 0.22 * load + 0.18 * ambient + 0.002 * rpm - 31 * warm + offset * 0.7
    coolant = 76 + 0.12 * load + 0.12 * ambient + 0.001 * rpm - 25 * warm + offset * 0.4
    pressure = 1.3 + 0.00085 * rpm - 0.009 * (oil - 80) + offset * 0.03
    voltage = 14.2 - 0.002 * load + offset * 0.01
    vibration = 0.42 + 0.00017 * rpm + 0.002 * load + offset * 0.02
    c = conditions or {}

    def loss(code):
        return np.broadcast_to(np.asarray(c.get(code, 0.0)), (n,))

    oil += 55 * loss("FC-01") ** 1.35 * (0.5 + load / 100)
    coolant += 47 * loss("FC-02") ** 1.3 * (0.55 + load / 100)
    pressure *= np.maximum(0.08, 1 - 0.92 * loss("FC-03"))
    voltage -= 3.7 * loss("FC-04")
    vibration *= 1 + 2.5 * loss("FC-05")
    for name, value, noise in zip(
        SENSORS, [oil, coolant, pressure, voltage, vibration], [0.65, 0.5, 0.035, 0.035, 0.025]
    ):
        f[name] = value + r.normal(0, noise, n)
    f["oil_temperature_c"] += r.normal(0, 0.3)  # per-vehicle sensor bias
    f["fuel_rate_lph"] = 0.7 + load * 0.075 + speed * 0.013
    f["odometer_km"] = vehicle["initial_odometer_km"] + np.cumsum(speed / 12)
    f["lifetime_engine_hours"] = vehicle["initial_engine_hours"] + (np.arange(n) + 1) / 12
    return f


def scenario(vehicle, kind, seed=44):
    ts = pd.date_range("2025-12-15 08:00", periods=43, freq="5min", tz="UTC")
    c = {}
    if kind in [f"FC-0{i}" for i in range(1, 6)]:
        c[kind] = np.where(np.arange(43) < 6, 0, 0.82)
    if kind == "multi_fault":
        c = {k: np.where(np.arange(43) < 6, 0, 0.85) for k in ["FC-01", "FC-04"]}
    f = observe(vehicle, ts, seed, c, high_load=kind == "healthy_high_load")
    if kind == "sensor_quality":
        f.loc[7:14, "quality_status"] = "sensor_error"
        f.loc[7:14, "oil_temperature_c"] += 80
    if kind == "missing_data":
        f.loc[7:14, "quality_status"] = "missing"
        f.loc[7:14, SENSORS] = np.nan
    return f


def daily_for(vehicle, seed, detailed=None):
    r = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", "2025-12-31", tz="UTC")
    n = len(dates)
    hours = r.gamma(2.1, 0.65, n)
    hours[r.random(n) < 0.12] = 0
    speed = r.uniform(24, 75, n)
    distance = hours * speed
    d = pd.DataFrame(
        dict(
            date=dates,
            vehicle_id=vehicle["vehicle_id"],
            operating_hours=hours,
            distance_km=distance,
            mean_oil_temperature_c=91 + r.normal(0, 2, n),
            mean_coolant_temperature_c=86 + r.normal(0, 1.5, n),
            mean_oil_pressure_bar=3 + r.normal(0, 0.15, n),
            mean_charging_voltage_v=14.1 + r.normal(0, 0.05, n),
            mean_engine_vibration_rms=0.9 + r.normal(0, 0.04, n),
            mean_ambient_temperature_c=9 + 12 * np.sin(dates.dayofyear.to_numpy() * 2 * np.pi / 365),
            mean_engine_load_pct=r.uniform(35, 65, n),
            condition_coverage=np.where(hours > 0, 0.95, 0),
        )
    )
    approximate = [c for c in d.columns if c.startswith("mean_")]
    d[approximate] = d[approximate].round(2)
    if detailed is not None:
        for date, g in detailed.groupby(detailed.timestamp.dt.floor("D")):
            mask = d.date == date
            d.loc[mask, "operating_hours"] = len(g) / 12
            d.loc[mask, "distance_km"] = (g.vehicle_speed_kmh / 12).sum()
            for sensor in SENSORS + ["ambient_temperature_c", "engine_load_pct"]:
                d.loc[mask, "mean_" + sensor] = g[sensor].mean()
            d.loc[mask, "condition_coverage"] = (g.quality_status == "valid").mean()
    d["odometer_km"] = vehicle["initial_odometer_km"] + d.distance_km.cumsum()
    d["lifetime_engine_hours"] = vehicle["initial_engine_hours"] + d.operating_hours.cumsum()
    d["source"] = "usage-synthetic-v1"
    d["simulation_version"] = VERSION
    return d


def full_day(vehicle, date, seed):
    r = np.random.default_rng(seed)
    n = int(r.integers(0, 43))
    ts = pd.date_range(date + pd.Timedelta(hours=7), periods=n, freq="5min")
    c = {}
    # Fault overlap independent of country; slow calendar degradation, abrupt loss and co-faults.
    for j in range(5):
        if (int(vehicle["vehicle_id"][-4:]) * 7 + j * 13) % 71 == 0:
            day = date.dayofyear
            c[f"FC-0{j + 1}"] = max(0, min(0.95, (day - 285) / 60))
    f = observe(vehicle, ts, seed, c)
    if n:
        f.loc[r.random(n) < 0.012, "quality_status"] = "missing"
        f.loc[f.quality_status == "missing", SENSORS] = np.nan
    return f


def generate(output=DATA, full=False, n=1000):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    from .ingestion import part_catalog

    part_catalog().to_parquet(output / "parts.parquet", index=False)
    a = assets(n)
    a.to_parquet(output / "assets.parquet", index=False)
    windows = []
    kinds = [
        "FC-01",
        "FC-02",
        "FC-03",
        "FC-04",
        "FC-05",
        "healthy_high_load",
        "sensor_quality",
        "missing_data",
        "multi_fault",
    ]
    for i, kind in enumerate(kinds):
        f = scenario(a.iloc[(11 if kind == "FC-02" and n >= 12 else i) % n], kind)
        f["scenario"] = kind
        windows.append(f)
    w = pd.concat(windows, ignore_index=True)
    w.to_parquet(output / "replays.parquet", index=False)
    daily = []
    for i, v in a.iterrows():
        detail = None
        if full:
            chunks = [
                full_day(v, date, SETTINGS.seed + i * 1000 + j)
                for j, date in enumerate(pd.date_range("2025-10-01", "2025-12-31", tz="UTC"))
            ]
            detail = pd.concat(chunks, ignore_index=True)
            p = output / "telemetry" / v.vehicle_id
            p.mkdir(parents=True, exist_ok=True)
        else:
            detail = w[w.vehicle_id == v.vehicle_id].copy()
        d = daily_for(v, SETTINGS.seed + i, detail if len(detail) else None)
        if len(detail):
            # Rebase detailed counters onto the same daily operating clock (including missing readings).
            for date, indices in detail.groupby(detail.timestamp.dt.floor("D")).groups.items():
                day = d[d.date == date].iloc[0]
                g = detail.loc[indices]
                detail.loc[indices, "odometer_km"] = (
                    day.odometer_km - day.distance_km + (g.vehicle_speed_kmh / 12).cumsum().to_numpy()
                )
                detail.loc[indices, "lifetime_engine_hours"] = (
                    day.lifetime_engine_hours - day.operating_hours + (np.arange(len(g)) + 1) / 12
                )
            if full:
                detail.to_parquet(p / "2025-Q4.parquet", index=False)
            else:
                w.loc[detail.index, ["odometer_km", "lifetime_engine_hours"]] = detail[
                    ["odometer_km", "lifetime_engine_hours"]
                ]
        daily.append(d)
    d = pd.concat(daily, ignore_index=True)
    d.to_parquet(output / "daily.parquet", index=False)
    if not full:
        w.to_parquet(output / "replays.parquet", index=False)
    d["month"] = d.date.dt.strftime("%Y-%m")
    m = (
        d.groupby(["vehicle_id", "month"])
        .agg(
            operating_hours=("operating_hours", "sum"),
            distance_km=("distance_km", "sum"),
            odometer_km=("odometer_km", "last"),
            lifetime_engine_hours=("lifetime_engine_hours", "last"),
            condition_coverage=("condition_coverage", "mean"),
        )
        .reset_index()
    )
    m["source"] = "daily-aggregation-v1"
    m.to_parquet(output / "monthly.parquet", index=False)
    # Export contracts preserve source IDs; canonical mapping is explicit.
    a[["crm_asset_id", "vehicle_id"]].assign(telemetry_asset_id="TEL-" + a.vehicle_id.str[-4:]).to_parquet(
        output / "id_map.parquet", index=False
    )
    september = d[d.date == pd.Timestamp("2025-09-01", tz="UTC")].set_index("vehicle_id")
    services = pd.DataFrame(
        [
            dict(
                service_id=f"HIST-{i}",
                vehicle_id=v.vehicle_id,
                completed_at="2025-09-01T12:00:00Z",
                package_id="INSPECTION-v1",
                completed_hours=float(september.loc[v.vehicle_id, "lifetime_engine_hours"]),
                completed_km=float(september.loc[v.vehicle_id, "odometer_km"]),
                source="mock-service-v1",
            )
            for i, v in a.iterrows()
        ]
    )
    services.to_parquet(output / "service_history.parquet", index=False)
    manifest = dict(
        simulation_version=VERSION,
        seed=SETTINGS.seed,
        fleet_size=n,
        full_detailed=full,
        daily_coverage="2025-01-01/2025-12-31",
        detailed_coverage="2025-10-01/2025-12-31"
        if full
        else "9 curated windows, 2025-12-15; 387 rows; 5-minute cadence",
        tables={p.name: len(pd.read_parquet(p)) for p in output.glob("*.parquet")},
        sha256={
            str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in output.rglob("*.parquet")
        },
    )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["tables"]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true")
    p.add_argument("--output", type=Path, default=DATA)
    p.add_argument("--vehicles", type=int, default=1000)
    args = p.parse_args()
    generate(args.output, args.full, args.vehicles)
