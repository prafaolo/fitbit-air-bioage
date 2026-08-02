import math

import pytest

from bioage.estimators.composite import combine, estimate_all
from bioage.estimators.models import BiomarkerVector, EstimatorResult
from bioage.types import Sex


def r(component: str, age: float, sigma: float) -> EstimatorResult:
    return EstimatorResult(component=component, age_years=age, sigma_years=sigma, inputs={})


def test_returns_none_with_fewer_than_two_components():
    assert combine([]) is None
    assert combine([r("kdm", 40.0, 5.0)]) is None


def test_equal_sigmas_produce_the_arithmetic_mean():
    result = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0)])
    assert result is not None
    assert result.age_years == pytest.approx(45.0)


def test_tighter_sigma_pulls_the_result_toward_it():
    result = combine([r("a", 40.0, 1.0), r("b", 60.0, 10.0)])
    assert result is not None
    assert result.age_years < 45.0


def test_inverse_variance_weighting_matches_hand_calculation():
    ages, sigmas = [40.0, 50.0], [4.0, 8.0]
    weights = [1 / s**2 for s in sigmas]
    expected = sum(a * w for a, w in zip(ages, weights, strict=True)) / sum(weights)
    result = combine([r("a", ages[0], sigmas[0]), r("b", ages[1], sigmas[1])])
    assert result is not None
    assert result.age_years == pytest.approx(expected)


def test_confidence_interval_is_symmetric_and_uses_1_96_sigma():
    sigmas = [4.0, 8.0]
    combined_sigma = math.sqrt(1 / sum(1 / s**2 for s in sigmas))
    result = combine([r("a", 40.0, sigmas[0]), r("b", 50.0, sigmas[1])])
    assert result is not None
    half_width = (result.ci_high - result.ci_low) / 2
    assert half_width == pytest.approx(1.96 * combined_sigma)
    assert result.age_years == pytest.approx((result.ci_low + result.ci_high) / 2)


def test_adding_a_component_narrows_the_interval():
    two = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0)])
    three = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0), r("c", 45.0, 5.0)])
    assert two is not None and three is not None
    assert (three.ci_high - three.ci_low) < (two.ci_high - two.ci_low)


def test_low_confidence_widens_the_interval_and_sets_the_flag():
    normal = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0)], low_confidence=False)
    thin = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0)], low_confidence=True)
    assert normal is not None and thin is not None
    assert thin.is_low_confidence is True
    assert normal.is_low_confidence is False
    assert (thin.ci_high - thin.ci_low) > (normal.ci_high - normal.ci_low)
    assert thin.age_years == pytest.approx(normal.age_years)


def test_component_weights_from_reference_are_applied():
    """Components listed in composite.yaml get their sigma scaled by the configured factor."""
    from bioage.reference.loader import get_composite

    assert set(get_composite().sigma_multipliers) <= {
        "ntnu_fitness", "hrv_norm", "steps_mortality", "kdm"
    }


def test_estimate_all_drops_components_whose_inputs_are_missing():
    """No waist means NTNU cannot run; the composite must still work."""
    v = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0, hrv_rmssd_ms=45.0,
        mean_daily_steps=9000.0, sleep_efficiency_pct=90.0, bmi=23.5, waist_cm=None,
    )
    result = estimate_all(v)
    assert result is not None
    assert "ntnu_fitness" not in {c.component for c in result.components}
    assert "hrv_norm" in {c.component for c in result.components}


def test_estimate_all_includes_all_four_when_everything_is_present():
    v = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0, hrv_rmssd_ms=45.0,
        mean_daily_steps=9000.0, sleep_efficiency_pct=90.0, bmi=23.5, waist_cm=88.0,
        active_zone_minutes_per_day=25.0,
    )
    result = estimate_all(v)
    assert result is not None
    assert {c.component for c in result.components} == {
        "ntnu_fitness", "hrv_norm", "steps_mortality", "kdm"
    }


def test_estimate_all_returns_none_when_almost_nothing_is_available():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0)
    assert estimate_all(v) is None
