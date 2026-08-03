"""Combine independent component estimates into one number with a confidence band.

Components are combined by inverse-variance weighting, which is the maximum-likelihood
combination of independent estimates of the same quantity:

    age   = sum(age_i / sigma_i^2) / sum(1 / sigma_i^2)
    sigma = sqrt(1 / sum(1 / sigma_i^2))

A composite is refused below `min_components`, because a single estimator dressed up as
a consensus would misrepresent its own uncertainty.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from bioage.estimators.hrv_norm import hrv_age
from bioage.estimators.kdm import kdm_age
from bioage.estimators.models import BiomarkerVector, EstimatorResult
from bioage.estimators.ntnu import fitness_age
from bioage.estimators.steps_mortality import steps_age
from bioage.reference.loader import get_composite

ESTIMATORS: Sequence[Callable[[BiomarkerVector], EstimatorResult | None]] = (
    fitness_age,
    hrv_age,
    steps_age,
    kdm_age,
)


@dataclass(frozen=True)
class CompositeResult:
    age_years: float
    ci_low: float
    ci_high: float
    components: list[EstimatorResult]
    is_low_confidence: bool


def combine(
    results: Sequence[EstimatorResult],
    low_confidence: bool = False,
) -> CompositeResult | None:
    """Inverse-variance combination of component estimates."""
    constants = get_composite()
    if len(results) < constants.min_components:
        return None

    weighted_sum = 0.0
    weight_total = 0.0
    for result in results:
        multiplier = constants.sigma_multipliers.get(result.component, 1.0)
        sigma = result.sigma_years * multiplier
        weight = 1.0 / sigma**2
        weighted_sum += result.age_years * weight
        weight_total += weight

    age = weighted_sum / weight_total
    sigma = math.sqrt(1.0 / weight_total)
    if low_confidence:
        sigma *= constants.low_confidence_sigma_multiplier

    half_width = constants.z_score * sigma
    return CompositeResult(
        age_years=age,
        ci_low=age - half_width,
        ci_high=age + half_width,
        components=list(results),
        is_low_confidence=low_confidence,
    )


def estimate_all(
    vector: BiomarkerVector,
    low_confidence: bool = False,
) -> CompositeResult | None:
    """Run every estimator whose inputs are available, then combine."""
    results = [result for estimator in ESTIMATORS if (result := estimator(vector)) is not None]
    return combine(results, low_confidence=low_confidence)
