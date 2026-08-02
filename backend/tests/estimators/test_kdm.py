import pytest

from bioage.estimators.kdm import BiomarkerReference, kdm_age, kdm_bio_age
from bioage.estimators.models import BiomarkerVector
from bioage.types import Sex

REFS = {
    "a": BiomarkerReference(name="a", q=50.0, k=0.30, s=6.0),
    "b": BiomarkerReference(name="b", q=20.0, k=-0.20, s=4.0),
    "c": BiomarkerReference(name="c", q=90.0, k=0.10, s=2.0),
}


def _on_the_line(age: float) -> dict[str, float]:
    """Observations lying exactly on each biomarker's reference regression."""
    return {name: ref.q + ref.k * age for name, ref in REFS.items()}


@pytest.mark.parametrize("age", [25.0, 40.0, 55.0, 70.0])
def test_subject_on_the_reference_regression_recovers_that_age(age):
    """The defining identity of KDM.

    If x_j = q_j + k_j*A for every biomarker, the estimator must return exactly A.
    This is the test that distinguishes the correct denominator (sum k^2/s^2) from the
    incorrect one (sum (k/s^2)^2) quoted in the source research document.
    """
    result = kdm_bio_age(_on_the_line(age), REFS, chronological_age=age, s_ba=None)
    assert result == pytest.approx(age, abs=1e-9)


def test_identity_holds_regardless_of_chronological_age_when_uncorrected():
    """Without the correction term, chronological age must not influence the result."""
    a = kdm_bio_age(_on_the_line(40.0), REFS, chronological_age=20.0, s_ba=None)
    b = kdm_bio_age(_on_the_line(40.0), REFS, chronological_age=80.0, s_ba=None)
    assert a == pytest.approx(b)


def test_correction_shrinks_estimate_toward_chronological_age():
    uncorrected = kdm_bio_age(_on_the_line(60.0), REFS, chronological_age=40.0, s_ba=None)
    corrected = kdm_bio_age(_on_the_line(60.0), REFS, chronological_age=40.0, s_ba=10.0)
    assert 40.0 < corrected < uncorrected


def test_smaller_s_ba_shrinks_harder():
    weak = kdm_bio_age(_on_the_line(60.0), REFS, chronological_age=40.0, s_ba=30.0)
    strong = kdm_bio_age(_on_the_line(60.0), REFS, chronological_age=40.0, s_ba=3.0)
    assert abs(strong - 40.0) < abs(weak - 40.0)


def test_biomarker_with_larger_residual_sd_has_less_influence():
    """Doubling s halves the weight k/s^2 twice over; the noisy marker should matter less."""
    noisy = {
        "a": BiomarkerReference(name="a", q=50.0, k=0.30, s=6.0),
        "b": BiomarkerReference(name="b", q=20.0, k=-0.20, s=40.0),
    }
    tight = {
        "a": BiomarkerReference(name="a", q=50.0, k=0.30, s=6.0),
        "b": BiomarkerReference(name="b", q=20.0, k=-0.20, s=4.0),
    }
    # 'a' says 60, 'b' says 30.
    obs = {"a": 50.0 + 0.30 * 60.0, "b": 20.0 - 0.20 * 30.0}
    with_noisy_b = kdm_bio_age(obs, noisy, chronological_age=45.0, s_ba=None)
    with_tight_b = kdm_bio_age(obs, tight, chronological_age=45.0, s_ba=None)
    assert abs(with_noisy_b - 60.0) < abs(with_tight_b - 60.0)


def test_ignores_observations_with_no_reference():
    a = kdm_bio_age(_on_the_line(50.0), REFS, chronological_age=50.0, s_ba=None)
    obs = _on_the_line(50.0) | {"unknown_marker": 12345.0}
    b = kdm_bio_age(obs, REFS, chronological_age=50.0, s_ba=None)
    assert a == pytest.approx(b)


def test_raises_when_no_biomarkers_overlap_the_references():
    with pytest.raises(ValueError, match="no biomarkers"):
        kdm_bio_age({"zzz": 1.0}, REFS, chronological_age=50.0, s_ba=None)


def test_rejects_zero_residual_sd():
    with pytest.raises(ValueError, match="s must be positive"):
        BiomarkerReference(name="bad", q=1.0, k=1.0, s=0.0)


def test_rejects_zero_slope():
    """A biomarker that does not change with age carries no age information."""
    with pytest.raises(ValueError, match="k must be non-zero"):
        BiomarkerReference(name="flat", q=1.0, k=0.0, s=1.0)


def test_kdm_age_returns_none_with_too_few_biomarkers():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0)
    assert kdm_age(v) is None


def test_kdm_age_produces_result_with_enough_biomarkers():
    v = BiomarkerVector(
        chronological_age=40.0,
        sex=Sex.MALE,
        resting_hr_bpm=60.0,
        hrv_rmssd_ms=45.0,
        mean_daily_steps=9000.0,
        sleep_efficiency_pct=90.0,
        bmi=23.5,
    )
    result = kdm_age(v)
    assert result is not None
    assert result.component == "kdm"
    assert 18.0 <= result.age_years <= 100.0
    assert result.sigma_years > 0


def test_kdm_age_worsening_every_biomarker_increases_the_estimate():
    healthy = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=52.0, hrv_rmssd_ms=65.0,
        mean_daily_steps=13000.0, sleep_efficiency_pct=94.0, bmi=22.0,
    )
    unhealthy = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=78.0, hrv_rmssd_ms=22.0,
        mean_daily_steps=2500.0, sleep_efficiency_pct=76.0, bmi=32.0,
    )
    good, bad = kdm_age(healthy), kdm_age(unhealthy)
    assert good is not None and bad is not None
    assert good.age_years < bad.age_years


def test_the_source_documents_denominator_does_not_satisfy_the_identity():
    """Regression guard: sum((k/s^2)^2) is the wrong denominator.

    reference-research-from-claude.md prints it that way. Recomputing with it here shows
    it fails to recover A, which is why the implementation uses sum(k^2/s^2).
    """
    age = 50.0
    obs = _on_the_line(age)
    numerator = sum((obs[n] - r.q) * (r.k / r.s**2) for n, r in REFS.items())
    wrong_denominator = sum((r.k / r.s**2) ** 2 for r in REFS.values())
    assert numerator / wrong_denominator != pytest.approx(age, abs=1.0)
