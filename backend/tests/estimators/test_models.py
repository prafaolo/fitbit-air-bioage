import pytest

from bioage.estimators.models import (
    AGE_CEILING,
    AGE_FLOOR,
    BiomarkerVector,
    EstimatorResult,
    clamp_age,
)
from bioage.types import Sex


def test_result_rejects_non_positive_sigma():
    with pytest.raises(ValueError, match="sigma_years must be positive"):
        EstimatorResult(component="ntnu", age_years=40.0, sigma_years=0.0, inputs={})


def test_result_rejects_implausible_age():
    with pytest.raises(ValueError, match="age_years out of plausible range"):
        EstimatorResult(component="ntnu", age_years=500.0, sigma_years=3.0, inputs={})


def test_result_accepts_valid_values():
    r = EstimatorResult(component="ntnu", age_years=38.2, sigma_years=3.5, inputs={"rhr": 58.0})
    assert r.component == "ntnu"
    assert r.inputs["rhr"] == 58.0


def test_clamp_age_bounds_below_and_above():
    assert clamp_age(5.0) == AGE_FLOOR
    assert clamp_age(140.0) == AGE_CEILING
    assert clamp_age(42.0) == 42.0


def test_biomarker_vector_allows_missing_optional_signals():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=58.0)
    assert v.waist_cm is None
    assert v.hrv_rmssd_ms is None
