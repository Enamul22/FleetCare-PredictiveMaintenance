"""Validated, versioned demonstration policies. Values are not vehicle service limits."""

from pathlib import Path
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/demo"
VERSION = "sim-1.0"
POLICY = "policy-1.0"
BASELINE = "healthy-linear-1.0"


class Settings(BaseModel):
    seed: int = 20251024
    fleet_size: int = Field(1000, ge=1, le=1000)
    cadence_minutes: int = Field(5, ge=1)
    minimum_coverage: float = Field(0.8, gt=0, le=1)
    max_gap_cadences: int = Field(2, ge=1)
    cooldown_minutes: int = Field(30, ge=0)


SETTINGS = Settings()
MODELS = {"ALD": "Alder Compact", "BIR": "Birch Sedan", "CED": "Cedar SUV", "ELM": "Elm Van"}
COUNTRIES = ["Finland", "Germany", "Spain", "United Kingdom"]
# code: sensor, evidence, warning, critical, warning minutes, recovery threshold, comparison
FAULTS = {
    "FC-01": ("oil_temperature_c", "difference", 15.0, 25.0, 10, 8.0, "Excessive oil temperature"),
    "FC-02": ("coolant_temperature_c", "difference", 12.0, 20.0, 10, 6.0, "Cooling-system overheating"),
    "FC-03": ("oil_pressure_bar", "ratio_low", 0.70, 0.50, 10, 0.85, "Insufficient oil pressure"),
    "FC-04": ("charging_voltage_v", "deficit", 1.0, 2.0, 10, 0.5, "Charging-system underperformance"),
    "FC-05": ("engine_vibration_rms", "ratio_high", 1.8, 2.5, 15, 1.3, "Excessive engine vibration"),
}
FAMILIES = {
    "FC-01": ["OIL-COOLER", "COOLER-SEALS", "OIL-TEMP-SENSOR"],
    "FC-02": ["THERMOSTAT", "COOLANT-PUMP", "FAN", "COOLANT-TEMP-SENSOR"],
    "FC-03": ["PRESSURE-SENSOR", "OIL-FILTER", "OIL-PUMP"],
    "FC-04": ["CONNECTION-KIT", "REGULATOR", "ALTERNATOR"],
    "FC-05": ["ENGINE-MOUNT", "IGNITION-COIL", "SPARK-PLUGS"],
}
TASKS = {
    "FC-01": "Review load and temperature; inspect fictional oil-cooling circuit and sensor bias.",
    "FC-02": "Inspect fictional circulation, thermostat and fan; verify sensor measurement.",
    "FC-03": "Verify pressure measurement; inspect fictional lubrication supply and filter.",
    "FC-04": "Inspect fictional charging connections and charging-component condition.",
    "FC-05": "Review RPM/load stability; inspect fictional mounting and ignition causes.",
}

SENSORS = [
    "oil_temperature_c",
    "coolant_temperature_c",
    "oil_pressure_bar",
    "charging_voltage_v",
    "engine_vibration_rms",
]
FEATURES = [
    "engine_load_pct",
    "ambient_temperature_c",
    "engine_rpm",
    "vehicle_speed_kmh",
    "warmup",
    "model_index",
]
