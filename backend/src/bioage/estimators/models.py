"""Value types shared by every estimator.

Estimators are pure: they consume a BiomarkerVector and return an EstimatorResult.
An estimate is never expressed without an accompanying sigma, because the composite
weights components by their inverse variance and the UI must always render a band.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bioage.types import Sex

AGE_FLOOR = 18.0
AGE_CEILING = 100.0


def clamp_age(value: float) -> float:
    """Constrain an estimate to a plausible adult range.

    Extrapolating a linear equation far outside its fitting range produces numbers
    that are arithmetically valid and biologically meaningless.
    """
    return min(max(value, AGE_FLOOR), AGE_CEILING)


@dataclass(frozen=True)
class EstimatorResult:
    """One component estimate: an age, its uncertainty, and the inputs behind it."""

    component: str
    age_years: float
    sigma_years: float
    inputs: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sigma_years <= 0:
            raise ValueError("sigma_years must be positive")
        if not 0 < self.age_years < 130:
            raise ValueError("age_years out of plausible range")


@dataclass(frozen=True)
class BiomarkerVector:
    """A 30-day rolling feature window plus subject identity.

    Every wearable-derived field is optional: coverage gaps are normal, and each
    estimator declares its own required subset.
    """

    chronological_age: float
    sex: Sex
    resting_hr_bpm: float | None = None
    hrv_rmssd_ms: float | None = None
    mean_daily_steps: float | None = None
    sleep_efficiency_pct: float | None = None
    sleep_regularity_min: float | None = None
    bmi: float | None = None
    waist_cm: float | None = None
    active_zone_minutes_per_day: float | None = None
    respiratory_rate_brpm: float | None = None
