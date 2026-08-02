"""Parsers for daily-aggregated data types.

Every parser is total: it returns None rather than raising when the payload is not the
type it handles or when the value field is absent. Missing days are the normal case for
a wearable, not an error condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from bioage.biomarkers.parsers.common import parse_double, parse_int64, parse_proto_date


@dataclass(frozen=True)
class ParsedPoint:
    day: date
    values: dict[str, float]


def _daily_body(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    body = payload.get(key)
    if not isinstance(body, dict) or "date" not in body:
        return None
    return body


def parse_daily_resting_heart_rate(payload: dict[str, Any]) -> ParsedPoint | None:
    body = _daily_body(payload, "dailyRestingHeartRate")
    if body is None:
        return None
    bpm = parse_int64(body.get("beatsPerMinute"))
    if bpm is None:
        return None
    return ParsedPoint(parse_proto_date(body["date"]), {"resting_hr_bpm": float(bpm)})


def parse_daily_heart_rate_variability(payload: dict[str, Any]) -> ParsedPoint | None:
    """Prefer deep-sleep RMSSD; the HRV-norm estimator is calibrated against RMSSD."""
    body = _daily_body(payload, "dailyHeartRateVariability")
    if body is None:
        return None
    rmssd = parse_double(body.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds"))
    average = parse_double(body.get("averageHeartRateVariabilityMilliseconds"))
    effective = rmssd if rmssd is not None else average
    if effective is None:
        return None
    values = {"hrv_rmssd_ms": effective}
    if average is not None:
        values["hrv_average_ms"] = average
    return ParsedPoint(parse_proto_date(body["date"]), values)


def parse_daily_respiratory_rate(payload: dict[str, Any]) -> ParsedPoint | None:
    body = _daily_body(payload, "dailyRespiratoryRate")
    if body is None:
        return None
    rate = parse_double(body.get("breathsPerMinute"))
    if rate is None:
        return None
    return ParsedPoint(parse_proto_date(body["date"]), {"respiratory_rate_brpm": rate})


def parse_daily_oxygen_saturation(payload: dict[str, Any]) -> ParsedPoint | None:
    body = _daily_body(payload, "dailyOxygenSaturation")
    if body is None:
        return None
    average = parse_double(body.get("averagePercentage"))
    if average is None:
        return None
    return ParsedPoint(parse_proto_date(body["date"]), {"spo2_pct": average})


def parse_daily_sleep_temperature_derivations(payload: dict[str, Any]) -> ParsedPoint | None:
    """Skin temperature is used only as a multi-week trend, never as a nightly value."""
    body = _daily_body(payload, "dailySleepTemperatureDerivations")
    if body is None:
        return None
    delta = parse_double(body.get("relativeNightlyStddev30dCelsius"))
    if delta is None:
        nightly = parse_double(body.get("nightlyTemperatureCelsius"))
        baseline = parse_double(body.get("baselineTemperatureCelsius"))
        if nightly is None or baseline is None:
            return None
        delta = nightly - baseline
    return ParsedPoint(parse_proto_date(body["date"]), {"skin_temp_delta_c": delta})
