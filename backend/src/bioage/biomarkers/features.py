"""Rolling-window feature computation.

Pure: takes daily records and profile scalars, returns a BiomarkerVector. Medians rather
than means throughout, because a single mis-measured night should not move a 30-day
estimate.

Two levels of gating apply. The window as a whole needs MIN_WINDOW_DAYS of data to
produce anything. Each biomarker additionally needs its own minimum number of days, so a
month with only five HRV nights does not contribute a confident-looking HRV age.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from bioage.biomarkers.regularity import sleep_regularity_minutes
from bioage.estimators.models import BiomarkerVector
from bioage.types import Sex

WINDOW_DAYS = 30
MIN_WINDOW_DAYS = 14
LOW_CONFIDENCE_DAYS = 21

MIN_RHR_DAYS = 10
MIN_HRV_DAYS = 10
MIN_STEPS_DAYS = 14
MIN_SLEEP_DAYS = 10


@dataclass(frozen=True)
class DailyRecord:
    day: date
    resting_hr_bpm: float | None = None
    hrv_rmssd_ms: float | None = None
    steps: float | None = None
    active_zone_minutes: float | None = None
    sleep_efficiency_pct: float | None = None
    sleep_midpoint_local_min: float | None = None
    respiratory_rate_brpm: float | None = None
    is_demo: bool = False


@dataclass(frozen=True)
class WindowCoverage:
    total_days: int
    rhr_days: int
    hrv_days: int
    steps_days: int
    sleep_days: int

    @property
    def is_low_confidence(self) -> bool:
        return self.total_days < LOW_CONFIDENCE_DAYS

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "total_days": self.total_days,
            "rhr_days": self.rhr_days,
            "hrv_days": self.hrv_days,
            "steps_days": self.steps_days,
            "sleep_days": self.sleep_days,
            "is_low_confidence": self.is_low_confidence,
        }


def window_records(
    records: Sequence[DailyRecord],
    window_end: date,
    window_days: int = WINDOW_DAYS,
) -> list[DailyRecord]:
    """Records in the half-open interval [window_end - window_days, window_end)."""
    start = window_end - timedelta(days=window_days)
    return [r for r in records if start <= r.day < window_end]


def _values(window: Sequence[DailyRecord], attribute: str) -> list[float]:
    return [value for r in window if (value := getattr(r, attribute)) is not None]


def _median_if_enough(
    window: Sequence[DailyRecord], attribute: str, minimum: int
) -> float | None:
    values = _values(window, attribute)
    return statistics.median(values) if len(values) >= minimum else None


def compute_coverage(window: Sequence[DailyRecord]) -> WindowCoverage:
    return WindowCoverage(
        total_days=len(window),
        rhr_days=len(_values(window, "resting_hr_bpm")),
        hrv_days=len(_values(window, "hrv_rmssd_ms")),
        steps_days=len(_values(window, "steps")),
        sleep_days=len(_values(window, "sleep_efficiency_pct")),
    )


def build_vector(
    window: Sequence[DailyRecord],
    chronological_age: float,
    sex: Sex,
    height_m: float | None,
    weight_kg: float | None,
    waist_cm: float | None,
) -> BiomarkerVector | None:
    """Aggregate a window into a BiomarkerVector, or None if the window is too thin."""
    if len(window) < MIN_WINDOW_DAYS:
        return None

    bmi = None
    if height_m and weight_kg and height_m > 0:
        bmi = weight_kg / (height_m**2)

    midpoints = _values(window, "sleep_midpoint_local_min")

    return BiomarkerVector(
        chronological_age=chronological_age,
        sex=sex,
        resting_hr_bpm=_median_if_enough(window, "resting_hr_bpm", MIN_RHR_DAYS),
        hrv_rmssd_ms=_median_if_enough(window, "hrv_rmssd_ms", MIN_HRV_DAYS),
        mean_daily_steps=_median_if_enough(window, "steps", MIN_STEPS_DAYS),
        sleep_efficiency_pct=_median_if_enough(window, "sleep_efficiency_pct", MIN_SLEEP_DAYS),
        sleep_regularity_min=sleep_regularity_minutes(midpoints),
        bmi=bmi,
        waist_cm=waist_cm,
        active_zone_minutes_per_day=_median_if_enough(window, "active_zone_minutes", 1),
        respiratory_rate_brpm=_median_if_enough(window, "respiratory_rate_brpm", 1),
    )
