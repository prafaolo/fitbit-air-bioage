"""Parsers for instantaneous sample data types.

Weight has two documented encodings in Google's Health API: the dataPoints overview
describes `weightGrams`, while the RPC reference describes `kilograms`. Both are accepted
and normalised to kilograms rather than guessing which one a given API version sends.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from bioage.biomarkers.parsers.common import parse_double, parse_timestamp
from bioage.biomarkers.parsers.daily import ParsedPoint


def _sample_day(body: dict[str, Any]) -> date | None:
    sample_time = body.get("sampleTime")
    if not isinstance(sample_time, dict) or "time" not in sample_time:
        return None
    return parse_timestamp(sample_time["time"]).date()


def parse_weight(payload: dict[str, Any]) -> ParsedPoint | None:
    body = payload.get("weight")
    if not isinstance(body, dict):
        return None
    day = _sample_day(body)
    if day is None:
        return None
    kilograms = parse_double(body.get("kilograms"))
    if kilograms is None:
        grams = parse_double(body.get("weightGrams"))
        if grams is None:
            return None
        kilograms = grams / 1000.0
    return ParsedPoint(day, {"weight_kg": kilograms})


def parse_height(payload: dict[str, Any]) -> ParsedPoint | None:
    body = payload.get("height")
    if not isinstance(body, dict):
        return None
    day = _sample_day(body)
    meters = parse_double(body.get("meters"))
    if day is None or meters is None:
        return None
    return ParsedPoint(day, {"height_m": meters})
