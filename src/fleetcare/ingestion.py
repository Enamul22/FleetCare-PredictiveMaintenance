"""Boundaries for three fictional source exports and canonical joins."""

import pandas as pd
from .config import DATA, MODELS, FAMILIES, VERSION


class Sources:
    def __init__(self, path=DATA):
        self.path = path

    def crm(self):
        a = pd.read_parquet(self.path / "assets.parquet")
        mapping = pd.read_parquet(self.path / "id_map.parquet")
        joined = a.merge(
            mapping[["crm_asset_id", "telemetry_asset_id"]], on="crm_asset_id", validate="one_to_one"
        )
        if len(joined) != len(a) or joined.vehicle_id.duplicated().any():
            raise ValueError("Incomplete canonical mapping")
        return joined

    def telemetry(self, scenario):
        f = pd.read_parquet(self.path / "replays.parquet")
        f = f[f.scenario == scenario].copy().sort_values("timestamp").reset_index(drop=True)
        mapping = pd.read_parquet(self.path / "id_map.parquet")
        canonical = f.drop(columns="vehicle_id").merge(
            mapping[["telemetry_asset_id", "vehicle_id"]], on="telemetry_asset_id", validate="many_to_one"
        )
        if len(canonical) != len(f):
            raise ValueError("Unmapped telemetry source ID")
        f = canonical
        known = set(self.crm().vehicle_id)
        if not set(f.vehicle_id) <= known:
            raise ValueError("Unmapped telemetry asset")
        return f

    def erp(self):
        return pd.read_parquet(self.path / "parts.parquet")


def part_catalog():
    return pd.DataFrame(
        [
            dict(
                sku=f"PART-{m}-{family}-01",
                erp_part_id=f"ERP-{m}-{family}",
                model_id=m,
                fault_code=code,
                component_type=code,
                family=family,
                quantity=1,
                stock=0 if (m == "ALD" and family == "THERMOSTAT") else 6,
                unit_price_eur=round(18 + (i + 1) * 24.5, 2),
                currency="EUR",
                supplier="Fictional Parts Cooperative",
                playbook_version="PB-1.0",
                source="mock-erp-v1",
                simulation_version=VERSION,
            )
            for m in MODELS
            for code, families in FAMILIES.items()
            for i, family in enumerate(families)
        ]
    )


def candidates(code, model, component_type, playbook="PB-1.0"):
    p = Sources().erp()
    return p[
        (p.fault_code == code)
        & (p.model_id == model)
        & (p.component_type == component_type)
        & (p.playbook_version == playbook)
    ]
