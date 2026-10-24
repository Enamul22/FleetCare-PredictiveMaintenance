"""Future-app exchange schemas only. No scheduler or FleetPulse score engine is implemented."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class ServicePackage(BaseModel):
    package_id: str
    model_id: Literal["ALD", "BIR", "CED", "ELM"]
    interval_hours: float = Field(gt=0)
    interval_km: float = Field(gt=0)
    interval_days: int = Field(gt=0)
    overlap_rule: Literal["combine", "keep_separate"]
    policy_version: str
    synthetic: Literal[True] = True


class ServiceCounter(BaseModel):
    vehicle_id: str
    package_id: str
    last_completed_at: datetime
    lifetime_hours_at_service: float = Field(ge=0)
    odometer_at_service_km: float = Field(ge=0)
    next_due_hours: float = Field(ge=0)
    next_due_km: float = Field(ge=0)
    next_due_at: datetime
    milestone_key: str
    late_service: bool
    policy_version: str


class MonthlyHealthRecord(BaseModel):
    vehicle_id: str
    month: str = Field(pattern=r"^2025-(0[1-9]|1[0-2])$")
    overall_condition_score: float | None = Field(default=None, ge=0, le=100)
    component_scores: dict[str, float | None]
    peer_percentile: float | None = Field(default=None, ge=0, le=100)
    data_confidence: float = Field(ge=0, le=1)
    peer_count: int = Field(ge=0)
    peer_reference: float | None = None
    cohort_definition: str
    fallback_group: str | None = None
    negative_contributors: list[dict]
    scoring_version: str
    reference_version: str
    revision: int = Field(ge=1)
    source_manifest_sha256: str
