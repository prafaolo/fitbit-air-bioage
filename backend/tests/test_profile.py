from datetime import date

import pytest

from bioage.db.models import DailyMetric, Measurement, Profile
from bioage.profile import age_on, resolve_profile
from bioage.types import Sex


@pytest.fixture
def seeded(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 1, 1)))
    db.flush()
    return db


def test_age_on_includes_the_fractional_year():
    assert age_on(date(1990, 1, 1), date(2026, 7, 2)) == pytest.approx(36.5, abs=0.02)


def test_age_on_is_exact_on_a_birthday():
    assert age_on(date(1990, 1, 1), date(2026, 1, 1)) == pytest.approx(36.0, abs=0.01)


def test_returns_none_when_no_profile_exists(db):
    assert resolve_profile(db, as_of=date(2026, 7, 1)) is None


def test_uses_the_latest_measurement_on_or_before_the_date(seeded):
    seeded.add_all([
        Measurement(kind="waist_cm", value=92.0, measured_on=date(2026, 1, 1)),
        Measurement(kind="waist_cm", value=88.0, measured_on=date(2026, 6, 1)),
    ])
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).waist_cm == pytest.approx(88.0)


def test_ignores_measurements_taken_after_the_date(seeded):
    """A waist measured in July must not rewrite a score for a week in May."""
    seeded.add_all([
        Measurement(kind="waist_cm", value=92.0, measured_on=date(2026, 1, 1)),
        Measurement(kind="waist_cm", value=80.0, measured_on=date(2026, 7, 1)),
    ])
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 5, 1)).waist_cm == pytest.approx(92.0)


def test_waist_is_none_when_never_measured(seeded):
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).waist_cm is None


def test_falls_back_to_api_weight_when_no_manual_measurement(seeded):
    seeded.add(DailyMetric(date=date(2026, 6, 15), weight_kg=76.5))
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).weight_kg == pytest.approx(76.5)


def test_manual_weight_takes_precedence_over_api_weight(seeded):
    seeded.add(DailyMetric(date=date(2026, 6, 15), weight_kg=76.5))
    seeded.add(Measurement(kind="weight_kg", value=74.0, measured_on=date(2026, 6, 1)))
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).weight_kg == pytest.approx(74.0)


def test_manual_weight_wins_even_when_the_api_value_is_more_recent(seeded):
    seeded.add(DailyMetric(date=date(2026, 6, 30), weight_kg=76.5))
    seeded.add(Measurement(kind="weight_kg", value=74.0, measured_on=date(2026, 1, 1)))
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).weight_kg == pytest.approx(74.0)


def test_resolves_sex_and_birthdate(seeded):
    resolved = resolve_profile(seeded, as_of=date(2026, 7, 1))
    assert resolved.sex is Sex.MALE
    assert resolved.birthdate == date(1990, 1, 1)
