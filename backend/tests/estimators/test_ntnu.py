import pytest

from bioage.estimators.models import BiomarkerVector
from bioage.estimators.ntnu import estimate_vo2max, fitness_age, physical_activity_index
from bioage.reference.loader import get_ntnu
from bioage.types import Sex


def test_vo2max_male_matches_hand_computed_published_equation():
    # 100.27 - 0.296*40 + 0.226*5 - 0.369*90 - 0.155*60
    expected = 100.27 - 0.296 * 40 + 0.226 * 5 - 0.369 * 90 - 0.155 * 60
    got = estimate_vo2max(
        age_years=40, sex=Sex.MALE, physical_activity=5, waist_cm=90, resting_hr_bpm=60
    )
    assert got == pytest.approx(expected)


def test_vo2max_female_matches_hand_computed_published_equation():
    expected = 74.74 - 0.247 * 40 + 0.198 * 5 - 0.259 * 80 - 0.114 * 65
    got = estimate_vo2max(
        age_years=40, sex=Sex.FEMALE, physical_activity=5, waist_cm=80, resting_hr_bpm=65
    )
    assert got == pytest.approx(expected)


@pytest.mark.parametrize("sex", [Sex.MALE, Sex.FEMALE])
@pytest.mark.parametrize("age", [25.0, 40.0, 62.0])
def test_round_trip_reference_inputs_return_chronological_age(sex, age):
    """A subject with exactly population-typical inputs must have fitness age == real age.

    This is the definitional identity of the estimator; if it fails, the inversion is
    inconsistent with the forward equation.
    """
    ref = get_ntnu().reference_population[sex]
    vector = BiomarkerVector(
        chronological_age=age,
        sex=sex,
        resting_hr_bpm=ref.resting_hr_bpm,
        waist_cm=ref.waist_cm,
        mean_daily_steps=None,
        active_zone_minutes_per_day=None,
    )
    result = fitness_age(vector, physical_activity_override=ref.physical_activity)
    assert result is not None
    assert result.age_years == pytest.approx(age, abs=1e-9)


def test_lower_resting_hr_never_increases_fitness_age():
    def age_for(rhr: float) -> float:
        v = BiomarkerVector(
            chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=rhr,
            waist_cm=90.0, mean_daily_steps=8000.0,
        )
        result = fitness_age(v)
        assert result is not None
        return result.age_years

    assert age_for(50.0) <= age_for(60.0) <= age_for(75.0)


def test_larger_waist_never_decreases_fitness_age():
    def age_for(waist: float) -> float:
        v = BiomarkerVector(
            chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0,
            waist_cm=waist, mean_daily_steps=8000.0,
        )
        result = fitness_age(v)
        assert result is not None
        return result.age_years

    assert age_for(80.0) <= age_for(95.0) <= age_for(110.0)


def test_returns_none_when_waist_missing():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0)
    assert fitness_age(v) is None


def test_returns_none_when_resting_hr_missing():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, waist_cm=90.0)
    assert fitness_age(v) is None


def test_physical_activity_index_is_monotonic_in_steps():
    a = physical_activity_index(3000, 0)
    b = physical_activity_index(8000, 0)
    c = physical_activity_index(15000, 0)
    assert a < b < c


def test_physical_activity_index_is_bounded():
    assert 0.0 <= physical_activity_index(0, 0) <= 15.0
    assert 0.0 <= physical_activity_index(40000, 300) <= 15.0


def test_physical_activity_index_falls_back_to_reference_when_no_data():
    v = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0, waist_cm=90.0
    )
    result = fitness_age(v)
    assert result is not None
    assert result.inputs["physical_activity"] == pytest.approx(5.0)


def test_result_reports_its_inputs_and_sigma():
    v = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=58.0,
        waist_cm=88.0, mean_daily_steps=10000.0,
    )
    result = fitness_age(v)
    assert result is not None
    assert result.component == "ntnu_fitness"
    assert result.sigma_years > 0
    assert set(result.inputs) >= {"resting_hr_bpm", "waist_cm", "physical_activity", "vo2max"}
