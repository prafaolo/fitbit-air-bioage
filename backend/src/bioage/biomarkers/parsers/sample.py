"""Parsers for instantaneous sample data types.

`sampleTime` has no top-level `time` field, despite what the RPC reference implies.
The live API nests a `civilTime.date` (already local, a `google.type.Date` object) and a
`physicalTime` (a UTC instant) inside it. `civilTime.date` is preferred for the day
because it is already in the user's local calendar; `physicalTime`'s date is a fallback
for payloads that omit `civilTime`.

Weight also has two documented encodings: the dataPoints overview describes
`weightGrams`, while the RPC reference describes `kilograms`. Both are accepted and
normalised to kilograms rather than guessing which one a given API version sends. Height
is analogous: the live API sends `heightMillimeters` (as a string), the RPC reference
describes `meters`; both are accepted and normalised to metres.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from bioage.biomarkers.parsers.common import parse_double, parse_proto_date, parse_timestamp
from bioage.biomarkers.parsers.daily import ParsedPoint


def _sample_day(body: dict[str, Any]) -> date | None:
    sample_time = body.get("sampleTime")
    if not isinstance(sample_time, dict):
        return None

    civil_time = sample_time.get("civilTime")
    if isinstance(civil_time, dict):
        civil_date = civil_time.get("date")
        if isinstance(civil_date, dict):
            try:
                return parse_proto_date(civil_date)
            except ValueError:
                pass

    physical_time = sample_time.get("physicalTime")
    if isinstance(physical_time, str):
        return parse_timestamp(physical_time).date()

    return None


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
    if day is None:
        return None
    meters = parse_double(body.get("meters"))
    if meters is None:
        millimeters = parse_double(body.get("heightMillimeters"))
        if millimeters is None:
            return None
        meters = millimeters / 1000.0
    return ParsedPoint(day, {"height_m": meters})
