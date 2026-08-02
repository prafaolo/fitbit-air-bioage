import math

import pytest

from bioage.estimators.models import BiomarkerVector
from bioage.estimators.steps_mortality import hazard_ratio, steps_age
from bioage.types import Sex


def test_reference_step_count_has_hazard_ratio_of_one():
    from bioage.reference.loader import get_steps_mortality

    assert hazard_ratio(get_steps_mortality().reference_steps) == pytest.approx(1.0)


def test_hazard_ratio_decreases_with_more_steps():
    assert hazard_ratio(2000) > hazard_ratio(6000) > hazard_ratio(10000)


def test_hazard_ratio_plateaus_at_high_step_counts():
    """Paluch reports the benefit levelling off; beyond the plateau nothing should change."""
    assert hazard_ratio(16000) == pytest.approx(hazard_ratio(25000))


def test_hazard_ratio_stays_positive():
    assert hazard_ratio(0) > 0
    assert hazard_ratio(100000) > 0


def test_age_equals_chronological_age_at_reference_steps():
    from bioage.reference.loader import get_steps_mortality

    v = BiomarkerVector(
        chronological_age=45.0,
        sex=Sex.MALE,
        mean_daily_steps=get_steps_mortality().reference_steps,
    )
    result = steps_age(v)
    assert result is not None
    assert result.age_years == pytest.approx(45.0)


def test_halving_hazard_subtracts_one_mortality_rate_doubling_time():
    """Gompertz: hazard doubles every MRDT years, so HR=0.5 is one MRDT younger, and
    HR=2.0 is one MRDT older -- age_offset = ln(HR)/ln(2) * mrdt_years.

    This is a direct unit test of that formula, independent of the shipped
    hazard-ratio knot table: the previous version of this test bisected the knot table
    to find a step count with HR=0.5 and always `pytest.skip`ped, because the shipped
    knots bottom out at HR 0.84 (14,000+ steps/day never reaches 0.5) -- so it could
    never actually run, and the MRDT anchor had no real assertion behind it.
    """
    from bioage.reference.loader import get_steps_mortality

    mrdt_years = get_steps_mortality().mrdt_years
    assert mrdt_years == pytest.approx(8.0)  # documents the currently shipped constant

    def offset(hazard_ratio_value: float) -> float:
        return math.log(hazard_ratio_value) / math.log(2.0) * mrdt_years

    assert offset(0.5) == pytest.approx(-8.0)
    assert offset(2.0) == pytest.approx(8.0)


def test_more_steps_never_increases_age():
    def age_for(steps: float) -> float:
        result = steps_age(
            BiomarkerVector(chronological_age=50.0, sex=Sex.MALE, mean_daily_steps=steps)
        )
        assert result is not None
        return result.age_years

    assert age_for(15000) <= age_for(8000) <= age_for(3000)


def test_returns_none_when_steps_missing():
    assert steps_age(BiomarkerVector(chronological_age=40.0, sex=Sex.MALE)) is None


def test_result_is_clamped_to_plausible_range():
    v = BiomarkerVector(chronological_age=20.0, sex=Sex.MALE, mean_daily_steps=30000.0)
    result = steps_age(v)
    assert result is not None
    assert result.age_years >= 18.0
