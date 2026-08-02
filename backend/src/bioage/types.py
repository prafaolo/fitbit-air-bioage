"""Shared value types with no dependencies on any other bioage module."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class Sex(StrEnum):
    """Biological sex, required by the sex-stratified NTNU and HRV equations."""

    MALE = "male"
    FEMALE = "female"


@dataclass(frozen=True)
class DateRange:
    """A half-open date interval: start inclusive, end exclusive."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("end must be after start")

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def chunked(self, max_days: int) -> Iterator[DateRange]:
        """Split into contiguous sub-ranges of at most `max_days` each.

        The Google Health API caps query ranges per data type (14 days for steps,
        90 for the rest), so any backfill longer than the cap must be issued as
        several sequential requests.
        """
        if max_days < 1:
            raise ValueError("max_days must be at least 1")
        cursor = self.start
        while cursor < self.end:
            stop = min(cursor + timedelta(days=max_days), self.end)
            yield DateRange(cursor, stop)
            cursor = stop
