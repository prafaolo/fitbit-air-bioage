"""The single source of truth for every Google-side constant.

Each data type is described once: its path segment, the field its filter expression must
reference, its documented query-range cap, the OAuth scope it needs, and the parser that
turns its payload into daily values.

Filter field names were confirmed against the live Google Health API docs on 2026-08-02:
- https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/list
  (verbatim filter examples and pagination defaults)
- https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints
  (per-message JSON field names and time-field types)
- https://developers.google.com/health/reference/rpc/google.devicesandservices.health.v4
  (proto field definitions for DailyRespiratoryRate, DailyVO2Max, ActiveZoneMinutes, Sleep)

The API launched in March 2026 and Google warned of breaking changes. Isolating these
constants here means a change on Google's side is a one-line edit rather than a hunt
through the codebase.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bioage.biomarkers.parsers.daily import (
    ParsedPoint,
    parse_daily_heart_rate_variability,
    parse_daily_oxygen_saturation,
    parse_daily_respiratory_rate,
    parse_daily_resting_heart_rate,
    parse_daily_sleep_temperature_derivations,
)
from bioage.biomarkers.parsers.interval import parse_active_zone_minutes, parse_steps
from bioage.biomarkers.parsers.sample import parse_height, parse_weight
from bioage.biomarkers.parsers.sleep import parse_sleep

METRICS_SCOPE = (
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly"
)
ACTIVITY_SCOPE = "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly"
SLEEP_SCOPE = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"

SCOPES = (METRICS_SCOPE, ACTIVITY_SCOPE, SLEEP_SCOPE)

DEFAULT_WINDOW_DAYS = 90
STEPS_WINDOW_DAYS = 14  # documented cap, unique to steps


def _noop(_: dict[str, Any]) -> ParsedPoint | None:
    return None


@dataclass(frozen=True)
class DataTypeSpec:
    data_type_id: str
    filter_field: str
    max_window_days: int
    scope: str
    parser: Callable[[dict[str, Any]], ParsedPoint | None]
    page_size: int = 1440
    expected_empty: bool = False


DATA_TYPES: tuple[DataTypeSpec, ...] = (
    DataTypeSpec(
        "daily-resting-heart-rate", "dailyRestingHeartRate.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_resting_heart_rate,
    ),
    # Verbatim in the list-method docs: dailyHeartRateVariability.date < "2024-08-15".
    DataTypeSpec(
        "daily-heart-rate-variability", "dailyHeartRateVariability.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_heart_rate_variability,
    ),
    DataTypeSpec(
        "daily-respiratory-rate", "dailyRespiratoryRate.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_respiratory_rate,
    ),
    DataTypeSpec(
        "daily-oxygen-saturation", "dailyOxygenSaturation.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_oxygen_saturation,
    ),
    DataTypeSpec(
        "daily-sleep-temperature-derivations", "dailySleepTemperatureDerivations.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_sleep_temperature_derivations,
    ),
    # Verbatim in the list-method docs: steps.interval.civil_start_time >= "2023-11-24".
    DataTypeSpec(
        "steps", "steps.interval.civil_start_time",
        STEPS_WINDOW_DAYS, ACTIVITY_SCOPE, parse_steps,
    ),
    # ActiveZoneMinutes' proto field is interval-typed (ObservationTimeInterval), same as
    # Steps; the interval.civil_start_time sub-path is documented as the generic pattern
    # for all interval-typed data types, not just steps.
    DataTypeSpec(
        "active-zone-minutes", "activeZoneMinutes.interval.civil_start_time",
        DEFAULT_WINDOW_DAYS, ACTIVITY_SCOPE, parse_active_zone_minutes,
    ),
    # CORRECTED from the task-19 brief's "sleep.session.end_time": the list-method docs
    # give the verbatim example `sleep.interval.end_time >= "2023-11-24T00:00:00Z"`. The
    # Sleep message's JSON field is named "session", but the filter DSL addresses it by
    # its interval type, not its JSON field name -- "session" in a filter is a 400.
    DataTypeSpec(
        "sleep", "sleep.interval.end_time",
        DEFAULT_WINDOW_DAYS, SLEEP_SCOPE, parse_sleep, page_size=25,
    ),
    # Verbatim in the list-method docs: weight.sample_time.physical_time >= "...".
    DataTypeSpec(
        "weight", "weight.sample_time.physical_time",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_weight,
    ),
    # Height's proto field is sample-typed (sampleTime), same as Weight; the
    # sample_time.physical_time sub-path is documented as the generic pattern for all
    # sample-typed data types, not just weight.
    DataTypeSpec(
        "height", "height.sample_time.physical_time",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_height,
    ),
    # Polled so the coverage table can confirm what the Air does not produce. The Fitbit
    # Air does not populate VO2max (Google derives it only from GPS-tracked runs), so this
    # entry uses a no-op parser and is expected to come back empty.
    DataTypeSpec(
        "daily-vo2-max", "dailyVo2Max.date",
        DEFAULT_WINDOW_DAYS, ACTIVITY_SCOPE, _noop, expected_empty=True,
    ),
)

_BY_ID = {spec.data_type_id: spec for spec in DATA_TYPES}


def get_spec(data_type_id: str) -> DataTypeSpec:
    return _BY_ID[data_type_id]
