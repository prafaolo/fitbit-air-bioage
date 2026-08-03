import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from bioage.biomarkers.parsers.daily import (
    parse_daily_heart_rate_variability,
    parse_daily_oxygen_saturation,
    parse_daily_respiratory_rate,
    parse_daily_resting_heart_rate,
    parse_daily_sleep_temperature_derivations,
)
from bioage.biomarkers.parsers.interval import parse_active_zone_minutes, parse_steps
from bioage.biomarkers.parsers.sample import parse_height, parse_weight

FIXTURES = Path(__file__).parent.parent / "fixtures" / "googlehealth"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())  # type: ignore[no-any-return]


def test_resting_heart_rate_coerces_the_string_int64() -> None:
    point = load("daily_resting_heart_rate")["dataPoints"][0]
    parsed = parse_daily_resting_heart_rate(point)
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)
    assert parsed.values["resting_hr_bpm"] == pytest.approx(58.0)


def test_hrv_prefers_deep_sleep_rmssd_over_the_average() -> None:
    point = load("daily_heart_rate_variability")["dataPoints"][0]
    parsed = parse_daily_heart_rate_variability(point)
    assert parsed is not None
    assert parsed.values["hrv_rmssd_ms"] == pytest.approx(46.7)
    assert parsed.values["hrv_average_ms"] == pytest.approx(41.2)


def test_hrv_falls_back_to_the_average_when_rmssd_is_absent() -> None:
    point = load("daily_heart_rate_variability")["dataPoints"][1]
    parsed = parse_daily_heart_rate_variability(point)
    assert parsed is not None
    assert parsed.values["hrv_rmssd_ms"] == pytest.approx(38.9)


def test_oxygen_saturation_uses_the_average_percentage() -> None:
    point = load("daily_oxygen_saturation")["dataPoints"][0]
    parsed = parse_daily_oxygen_saturation(point)
    assert parsed is not None
    assert parsed.values["spo2_pct"] == pytest.approx(96.4)


def test_respiratory_rate_uses_the_breaths_per_minute_double() -> None:
    point = load("daily_respiratory_rate")["dataPoints"][0]
    parsed = parse_daily_respiratory_rate(point)
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)
    assert parsed.values["respiratory_rate_brpm"] == pytest.approx(14.8)


def test_respiratory_rate_returns_none_when_breaths_per_minute_is_missing() -> None:
    point = {"dailyRespiratoryRate": {"date": {"year": 2026, "month": 6, "day": 1}}}
    assert parse_daily_respiratory_rate(point) is None


def test_steps_coerces_the_string_count_and_dates_by_interval_start() -> None:
    point = load("steps")["dataPoints"][0]
    parsed = parse_steps(point)
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)
    assert parsed.values["steps"] == pytest.approx(10432.0)


def test_sleep_temperature_uses_the_relative_nightly_deviation() -> None:
    point = {
        "dailySleepTemperatureDerivations": {
            "date": {"year": 2026, "month": 6, "day": 1},
            "nightlyTemperatureCelsius": 33.8,
            "baselineTemperatureCelsius": 33.5,
            "relativeNightlyStddev30dCelsius": 0.3,
        }
    }
    parsed = parse_daily_sleep_temperature_derivations(point)
    assert parsed is not None
    assert parsed.values["skin_temp_delta_c"] == pytest.approx(0.3)


def test_active_zone_minutes_coerces_the_string_count() -> None:
    point = {
        "activeZoneMinutes": {
            "interval": {
                "startTime": "2026-06-01T00:00:00Z",
                "endTime": "2026-06-02T00:00:00Z",
            },
            "heartRateZone": "FAT_BURN",
            "activeZoneMinutes": "27",
        }
    }
    parsed = parse_active_zone_minutes(point)
    assert parsed is not None
    assert parsed.values["active_zone_minutes"] == pytest.approx(27.0)


def test_weight_uses_civil_time_date_and_weight_grams_from_a_real_payload() -> None:
    """Real captured payload: sampleTime has no top-level `time` field -- the day comes
    from sampleTime.civilTime.date (already local), and the value is weightGrams, not
    the RPC-documented `kilograms`."""
    point = load("weight")["dataPoints"][0]
    parsed = parse_weight(point)
    assert parsed is not None
    assert parsed.day == date(2026, 7, 8)
    assert parsed.values["weight_kg"] == pytest.approx(88.0)


def test_weight_second_real_payload() -> None:
    point = load("weight")["dataPoints"][1]
    parsed = parse_weight(point)
    assert parsed is not None
    assert parsed.day == date(2026, 6, 16)
    assert parsed.values["weight_kg"] == pytest.approx(87.0)


def test_height_uses_civil_time_date_and_height_millimeters_from_a_real_payload() -> None:
    """Real captured payload: heightMillimeters is a string ("1900"), not the
    RPC-documented `meters`."""
    point = load("height")["dataPoints"][0]
    parsed = parse_height(point)
    assert parsed is not None
    assert parsed.day == date(2026, 6, 16)
    assert parsed.values["height_m"] == pytest.approx(1.9)


def test_weight_accepts_the_kilograms_encoding_as_a_fallback() -> None:
    """The RPC reference documents `kilograms`; the live API sends `weightGrams`, but
    `kilograms` is kept as a fallback in case a future API version sends it."""
    parsed = parse_weight(
        {
            "weight": {
                "sampleTime": {"civilTime": {"date": {"year": 2026, "month": 6, "day": 1}}},
                "kilograms": 74.3,
            }
        }
    )
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)
    assert parsed.values["weight_kg"] == pytest.approx(74.3)


def test_height_accepts_the_meters_encoding_as_a_fallback() -> None:
    """The RPC reference documents `meters`; the live API sends `heightMillimeters`,
    but `meters` is kept as a fallback in case a future API version sends it."""
    parsed = parse_height(
        {
            "height": {
                "sampleTime": {"civilTime": {"date": {"year": 2026, "month": 6, "day": 1}}},
                "meters": 1.78,
            }
        }
    )
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)
    assert parsed.values["height_m"] == pytest.approx(1.78)


def test_sample_day_falls_back_to_physical_time_when_civil_time_is_absent() -> None:
    parsed = parse_weight(
        {
            "weight": {
                "sampleTime": {"physicalTime": "2026-06-01T07:30:00Z"},
                "weightGrams": 74300,
            }
        }
    )
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)
    assert parsed.values["weight_kg"] == pytest.approx(74.3)


@pytest.mark.parametrize(
    "parser",
    [
        parse_daily_resting_heart_rate,
        parse_daily_heart_rate_variability,
        parse_daily_respiratory_rate,
        parse_daily_oxygen_saturation,
        parse_steps,
        parse_weight,
        parse_height,
    ],
)
def test_every_parser_returns_none_for_an_unrelated_payload(
    parser: Any,
) -> None:
    assert parser({"somethingElse": {}}) is None


def test_parser_returns_none_when_the_value_field_is_missing() -> None:
    point = {"dailyRestingHeartRate": {"date": {"year": 2026, "month": 6, "day": 1}}}
    assert parse_daily_resting_heart_rate(point) is None
