"""Coercion helpers for Google Health API proto-JSON encoding.

Three encoding quirks bite repeatedly:
  * `google.type.Date` is an object {year, month, day}, not an ISO-8601 string.
  * `google.protobuf.Duration` is a string with a trailing 's', e.g. "28800s".
  * `int64` fields are JSON *strings*, because JSON numbers cannot hold 64-bit integers
    safely. Reading them as numbers works until it silently does not.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def parse_proto_date(value: dict[str, Any]) -> date:
    try:
        return date(int(value["year"]), int(value["month"]), int(value["day"]))
    except KeyError as exc:
        raise ValueError(f"incomplete proto Date: {value!r}") from exc


def parse_duration_seconds(value: str) -> float:
    if not isinstance(value, str) or not value.endswith("s"):
        raise ValueError(f"duration must end with 's': {value!r}")
    return float(value[:-1])


def parse_int64(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"int64 does not accept bool: {value!r}")
    if isinstance(value, float):
        raise ValueError(f"int64 does not accept float: {value!r}")
    if isinstance(value, (str, int)):
        return int(value)
    raise ValueError(f"int64 must be str, int, or None: {value!r}")


def parse_double(value: float | str | None) -> float | None:
    if value is None:
        return None
    return float(value)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone: {value!r}")
    return parsed
