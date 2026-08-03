"""Non-exercise fitness age from the HUNT Fitness Study VO2max equations.

The Fitbit Air produces no usable VO2max (Google derives it only from GPS-tracked runs),
so this estimator uses the non-exercise form, which needs only age, sex, waist
circumference, resting heart rate and a physical-activity index.

Fitness age is defined by inverting the same equation at population-typical activity,
waist and resting HR: it is the age at which a typical person would have the subject's
estimated VO2max. Using one equation in both directions guarantees the round-trip
identity `fitness_age(vo2max(age, reference inputs)) == age`.
"""

from __future__ import annotations

from bioage.estimators.models import BiomarkerVector, EstimatorResult, clamp_age
from bioage.reference.loader import get_ntnu, get_pa_index
from bioage.types import Sex

COMPONENT = "ntnu_fitness"


def _interpolate(knots: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation, clamped at both ends."""
    if x <= knots[0][0]:
        return knots[0][1]
    if x >= knots[-1][0]:
        return knots[-1][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:], strict=False):
        if x0 <= x <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (y1 - y0) * (x - x0) / span
    return knots[-1][1]


def physical_activity_index(
    mean_daily_steps: float | None,
    active_zone_minutes_per_day: float | None,
) -> float:
    """Approximate the HUNT questionnaire activity index from wearable activity.

    This is the weakest input in the estimator; see reference/pa_index.yaml.
    """
    constants = get_pa_index()
    base = _interpolate(constants.steps_knots, mean_daily_steps or 0.0)
    bonus = _interpolate(constants.azm_knots, active_zone_minutes_per_day or 0.0)
    return min(base + bonus, constants.index_ceiling)


def estimate_vo2max(
    *,
    age_years: float,
    sex: Sex,
    physical_activity: float,
    waist_cm: float,
    resting_hr_bpm: float,
) -> float:
    """Non-exercise VO2max estimate in mL/kg/min."""
    c = get_ntnu().coefficients[sex]
    return (
        c.intercept
        + c.age * age_years
        + c.physical_activity * physical_activity
        + c.waist * waist_cm
        + c.resting_hr * resting_hr_bpm
    )


def fitness_age(
    vector: BiomarkerVector,
    physical_activity_override: float | None = None,
) -> EstimatorResult | None:
    """Return the NTNU fitness age, or None if required inputs are unavailable."""
    if vector.waist_cm is None or vector.resting_hr_bpm is None:
        return None

    constants = get_ntnu()
    coeff = constants.coefficients[vector.sex]
    reference = constants.reference_population[vector.sex]

    if physical_activity_override is not None:
        activity = physical_activity_override
    elif vector.mean_daily_steps is None and vector.active_zone_minutes_per_day is None:
        activity = get_pa_index().fallback_index
    else:
        activity = physical_activity_index(
            vector.mean_daily_steps, vector.active_zone_minutes_per_day
        )

    vo2max = estimate_vo2max(
        age_years=vector.chronological_age,
        sex=vector.sex,
        physical_activity=activity,
        waist_cm=vector.waist_cm,
        resting_hr_bpm=vector.resting_hr_bpm,
    )

    # Invert the same equation at reference inputs and solve for age.
    # vo2max = intercept + age*A + pa*PA_ref + waist*WC_ref + rhr*RHR_ref
    baseline = (
        coeff.intercept
        + coeff.physical_activity * reference.physical_activity
        + coeff.waist * reference.waist_cm
        + coeff.resting_hr * reference.resting_hr_bpm
    )
    age = (vo2max - baseline) / coeff.age  # coeff.age is negative

    return EstimatorResult(
        component=COMPONENT,
        age_years=clamp_age(age),
        sigma_years=get_pa_index().fitness_age_sigma_years,
        inputs={
            "resting_hr_bpm": vector.resting_hr_bpm,
            "waist_cm": vector.waist_cm,
            "physical_activity": activity,
            "vo2max": vo2max,
        },
    )
