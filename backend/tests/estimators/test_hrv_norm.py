import pytest

from bioage.estimators.hrv_norm import expected_rmssd, hrv_age
from bioage.estimators.models import BiomarkerVector
from bioage.types import Sex


@pytest.mark.parametrize(
    ("age", "approx_rmssd"),
    [(25.0, 60.0), (45.0, 43.0), (55.0, 34.0), (65.0, 31.0)],
)
def test_expected_rmssd_tracks_published_normative_medians(age, approx_rmssd):
    """The fitted curve must stay close to the normative medians it was fitted to."""
    assert expected_rmssd(age, Sex.MALE) == pytest.approx(approx_rmssd, rel=0.15)


def test_expected_rmssd_declines_monotonically_with_age():
    values = [expected_rmssd(a, Sex.MALE) for a in range(20, 80, 5)]
    assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("age", [30.0, 45.0, 60.0])
def test_round_trip_normative_rmssd_returns_that_age(age):
    """Feeding the norm for an age back in must recover that age."""
    v = BiomarkerVector(
        chronological_age=age, sex=Sex.MALE, hrv_rmssd_ms=expected_rmssd(age, Sex.MALE)
    )
    result = hrv_age(v)
    assert result is not None
    assert result.age_years == pytest.approx(age, abs=1e-6)


def test_higher_rmssd_never_increases_hrv_age():
    def age_for(rmssd: float) -> float:
        result = hrv_age(
            BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, hrv_rmssd_ms=rmssd)
        )
        assert result is not None
        return result.age_years

    assert age_for(70.0) <= age_for(45.0) <= age_for(25.0)


def test_returns_none_when_rmssd_missing():
    assert hrv_age(BiomarkerVector(chronological_age=40.0, sex=Sex.MALE)) is None


def test_rejects_non_positive_rmssd():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, hrv_rmssd_ms=0.0)
    assert hrv_age(v) is None


def test_extreme_rmssd_is_clamped_not_extrapolated_absurdly():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, hrv_rmssd_ms=400.0)
    result = hrv_age(v)
    assert result is not None
    assert 18.0 <= result.age_years <= 100.0


def test_sigma_reflects_wrist_ppg_noise_and_exceeds_ntnu_precision():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, hrv_rmssd_ms=45.0)
    result = hrv_age(v)
    assert result is not None
    assert result.sigma_years >= 6.0
