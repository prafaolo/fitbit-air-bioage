"""Mortality-equivalent age from daily step volume.

Two published results are composed:

1. Paluch et al. 2022 give an all-cause mortality hazard ratio as a function of mean
   daily steps, plateauing at high step counts.
2. The Gompertz law states adult mortality hazard doubles roughly every 8 years.

Together: a hazard ratio HR corresponds to an age offset of ln(HR)/ln(2) * MRDT years.
A person walking the reference step count sits exactly at their chronological age.
"""

from __future__ import annotations

import math

from bioage.estimators.models import BiomarkerVector, EstimatorResult, clamp_age
from bioage.reference.loader import get_steps_mortality

COMPONENT = "steps_mortality"


def _interpolate(knots: list[tuple[float, float]], x: float) -> float:
    if x <= knots[0][0]:
        return knots[0][1]
    if x >= knots[-1][0]:
        return knots[-1][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:], strict=False):
        if x0 <= x <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (y1 - y0) * (x - x0) / span
    return knots[-1][1]


def hazard_ratio(mean_daily_steps: float) -> float:
    """All-cause mortality hazard ratio relative to the reference step count."""
    return _interpolate(get_steps_mortality().hazard_knots, max(mean_daily_steps, 0.0))


def steps_age(vector: BiomarkerVector) -> EstimatorResult | None:
    """Return the step-count mortality-equivalent age, or None if steps are missing."""
    steps = vector.mean_daily_steps
    if steps is None:
        return None

    constants = get_steps_mortality()
    ratio = hazard_ratio(steps)
    offset = math.log(ratio) / math.log(2.0) * constants.mrdt_years
    age = vector.chronological_age + offset

    return EstimatorResult(
        component=COMPONENT,
        age_years=clamp_age(age),
        sigma_years=constants.sigma_years,
        inputs={"mean_daily_steps": steps, "hazard_ratio": ratio, "age_offset": offset},
    )
