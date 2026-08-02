"""HRV age: invert nightly RMSSD against age/sex normative medians.

RMSSD declines roughly log-linearly with age after the mid-20s. Fitting
ln(RMSSD) = a + b*age lets the estimate be inverted in closed form:
    age = (ln(RMSSD) - a) / b

Fitbit computes HRV only during sleep, and consumer wrist PPG HRV is materially noisier
than ECG, so this component carries a deliberately wide sigma.
"""

from __future__ import annotations

import math

from bioage.estimators.models import BiomarkerVector, EstimatorResult, clamp_age
from bioage.reference.loader import get_hrv_norms
from bioage.types import Sex

COMPONENT = "hrv_norm"


def expected_rmssd(age_years: float, sex: Sex) -> float:
    """Normative nightly RMSSD in milliseconds for a given age and sex."""
    fit = get_hrv_norms().fit_for(sex)
    return math.exp(fit.ln_intercept + fit.ln_slope * age_years)


def hrv_age(vector: BiomarkerVector) -> EstimatorResult | None:
    """Return the HRV-norm age, or None if RMSSD is unavailable or implausible."""
    rmssd = vector.hrv_rmssd_ms
    constants = get_hrv_norms()
    if rmssd is None or rmssd <= 0:
        return None

    bounded = min(max(rmssd, constants.min_rmssd_ms), constants.max_rmssd_ms)
    fit = constants.fit_for(vector.sex)
    age = (math.log(bounded) - fit.ln_intercept) / fit.ln_slope

    return EstimatorResult(
        component=COMPONENT,
        age_years=clamp_age(age),
        sigma_years=constants.sigma_years,
        inputs={
            "hrv_rmssd_ms": rmssd,
            "expected_rmssd_ms": expected_rmssd(vector.chronological_age, vector.sex),
        },
    )
