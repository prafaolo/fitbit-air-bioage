"""Pydantic response and request models for the HTTP API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bioage.db.models import MEASUREMENT_KINDS
from bioage.types import Sex


class ComponentOut(BaseModel):
    component: str
    age_years: float
    sigma_years: float
    inputs: dict[str, float]


class SeriesPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week_start: date
    chronological_age: float
    composite_age: float
    ci_low: float
    ci_high: float
    is_low_confidence: bool
    components: list[ComponentOut]


class WeekDetail(SeriesPoint):
    coverage: dict


class MeasurementIn(BaseModel):
    kind: str
    value: float = Field(gt=0)
    measured_on: date

    @field_validator("kind")
    @classmethod
    def known_kind(cls, value: str) -> str:
        if value not in MEASUREMENT_KINDS:
            raise ValueError(f"kind must be one of {MEASUREMENT_KINDS}")
        return value


class MeasurementOut(MeasurementIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ProfileIn(BaseModel):
    sex: Sex
    birthdate: date

    @field_validator("birthdate")
    @classmethod
    def not_in_the_future(cls, value: date) -> date:
        if value >= date.today():
            raise ValueError("birthdate must be in the past")
        return value


class ProfileOut(BaseModel):
    sex: Sex
    birthdate: date
    measurements: list[MeasurementOut]


class DailyMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    resting_hr_bpm: float | None
    hrv_rmssd_ms: float | None
    steps: int | None
    sleep_efficiency_pct: float | None


class CoverageOut(BaseModel):
    data_type: str
    synced_through: date | None
    last_run_at: str | None
    last_error: str | None
    expected_empty: bool
    points_stored: int


class SyncStatusOut(BaseModel):
    connected: bool
    data_types: list[CoverageOut]
