"""Klemera-Doubal biological age.

For each biomarker j, the reference population satisfies x_j = q_j + k_j * age, with
residual standard deviation s_j. The Klemera-Doubal estimator inverts that system:

    BA_E = sum_j[(x_j - q_j) * k_j / s_j^2] / sum_j[k_j^2 / s_j^2]

and the corrected form pulls the estimate toward chronological age (CA) using the
characteristic variance s_BA^2:

    BA_EC = [sum_j((x_j - q_j) k_j / s_j^2) + CA / s_BA^2]
          / [sum_j(k_j^2 / s_j^2)          + 1  / s_BA^2]

The denominator squares k_j, not k_j/s_j^2. That distinction is load-bearing: only this
form satisfies BA_E == A when every biomarker sits exactly on its regression line.

The same denominator is Fisher information about age, so KDM's own uncertainty is not a
fixed constant: it shrinks as more, or more age-informative, biomarkers are supplied.

    sigma = sqrt( 1 / ( sum_j(k_j^2 / s_j^2) + 1/s_BA^2 ) )

with the 1/s_BA^2 term dropped when no chronological-age correction is applied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bioage.estimators.models import BiomarkerVector, EstimatorResult, clamp_age
from bioage.reference.loader import get_kdm

COMPONENT = "kdm"


@dataclass(frozen=True)
class BiomarkerReference:
    """Reference regression of one biomarker on chronological age."""

    name: str
    q: float
    k: float
    s: float

    def __post_init__(self) -> None:
        if self.s <= 0:
            raise ValueError("s must be positive")
        if self.k == 0:
            raise ValueError("k must be non-zero")


def _biomarker_information(
    observations: dict[str, float],
    references: dict[str, BiomarkerReference],
) -> tuple[float, int]:
    """Return (sum_j k_j^2/s_j^2, count of overlapping biomarkers).

    This sum is the Fisher information about age carried by the biomarkers alone,
    shared by both the estimate's denominator and its realized-information sigma.
    """
    denominator = 0.0
    used = 0
    for name in observations:
        ref = references.get(name)
        if ref is None:
            continue
        denominator += ref.k**2 / ref.s**2
        used += 1
    return denominator, used


def _correction_information(s_ba: float | None) -> float:
    if s_ba is None:
        return 0.0
    if s_ba <= 0:
        raise ValueError("s_ba must be positive")
    return 1.0 / s_ba**2


def kdm_bio_age(
    observations: dict[str, float],
    references: dict[str, BiomarkerReference],
    chronological_age: float,
    s_ba: float | None,
) -> float:
    """Compute BA_E, or BA_EC when s_ba is supplied.

    Observations without a matching reference are ignored.
    """
    denominator, used = _biomarker_information(observations, references)
    if used == 0:
        raise ValueError("no biomarkers overlap the supplied references")

    numerator = 0.0
    for name, value in observations.items():
        ref = references.get(name)
        if ref is None:
            continue
        numerator += (value - ref.q) * (ref.k / ref.s**2)

    if s_ba is not None:
        correction = _correction_information(s_ba)
        numerator += chronological_age * correction
        denominator += correction

    return numerator / denominator


def kdm_sigma(
    observations: dict[str, float],
    references: dict[str, BiomarkerReference],
    s_ba: float | None,
) -> float:
    """Realized-information uncertainty of the KDM estimate.

    sqrt(1 / (sum_j k_j^2/s_j^2 [+ 1/s_BA^2])) -- the same denominator kdm_bio_age uses,
    read as Fisher information rather than a weighted-average denominator. Fewer, or
    less age-informative, biomarkers mean less information and a larger sigma.
    """
    denominator, used = _biomarker_information(observations, references)
    if used == 0:
        raise ValueError("no biomarkers overlap the supplied references")

    denominator += _correction_information(s_ba)
    return math.sqrt(1.0 / denominator)


def _observations(vector: BiomarkerVector) -> dict[str, float]:
    candidates = {
        "resting_hr_bpm": vector.resting_hr_bpm,
        "hrv_rmssd_ms": vector.hrv_rmssd_ms,
        "mean_daily_steps": vector.mean_daily_steps,
        "sleep_efficiency_pct": vector.sleep_efficiency_pct,
        "bmi": vector.bmi,
    }
    return {name: value for name, value in candidates.items() if value is not None}


def kdm_age(vector: BiomarkerVector) -> EstimatorResult | None:
    """Return the KDM biological age, or None if too few biomarkers are available."""
    constants = get_kdm()
    references = {
        name: BiomarkerReference(name=name, q=marker.q, k=marker.k, s=marker.s)
        for name, marker in constants.biomarkers.items()
    }
    observations = {
        name: value for name, value in _observations(vector).items() if name in references
    }
    if len(observations) < constants.min_biomarkers:
        return None

    age = kdm_bio_age(
        observations, references, chronological_age=vector.chronological_age, s_ba=constants.s_ba
    )
    sigma = kdm_sigma(observations, references, s_ba=constants.s_ba)
    return EstimatorResult(
        component=COMPONENT,
        age_years=clamp_age(age),
        sigma_years=sigma,
        inputs={**observations, "biomarker_count": float(len(observations))},
    )
