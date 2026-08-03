"""Parsers for interval data types, attributed to the interval's start date."""

from __future__ import annotations

from datetime import date
from typing import Any

from bioage.biomarkers.parsers.common import parse_int64, parse_timestamp
from bioage.biomarkers.parsers.daily import ParsedPoint


def _interval_start_day(body: dict[str, Any]) -> date | None:
    interval = body.get("interval")
    if not isinstance(interval, dict) or "startTime" not in interval:
        return None
    return parse_timestamp(interval["startTime"]).date()


def parse_steps(payload: dict[str, Any]) -> ParsedPoint | None:
    body = payload.get("steps")
    if not isinstance(body, dict):
        return None
    day = _interval_start_day(body)
    count = parse_int64(body.get("count"))
    if day is None or count is None:
        return None
    return ParsedPoint(day, {"steps": float(count)})


def parse_active_zone_minutes(payload: dict[str, Any]) -> ParsedPoint | None:
    body = payload.get("activeZoneMinutes")
    if not isinstance(body, dict):
        return None
    day = _interval_start_day(body)
    minutes = parse_int64(body.get("activeZoneMinutes"))
    if day is None or minutes is None:
        return None
    return ParsedPoint(day, {"active_zone_minutes": float(minutes)})
