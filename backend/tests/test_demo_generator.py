from datetime import date

import pytest

from bioage.db.models import BioAgeScore, DailyMetric, Profile
from bioage.demo.generator import generate_daily_metrics, seed_demo


def test_generator_is_deterministic_for_a_given_seed():
    a = generate_daily_metrics(date(2026, 1, 1), days=30, seed=7)
    b = generate_daily_metrics(date(2026, 1, 1), days=30, seed=7)
    assert [m.resting_hr_bpm for m in a] == [m.resting_hr_bpm for m in b]


def test_different_seeds_produce_different_data():
    a = generate_daily_metrics(date(2026, 1, 1), days=30, seed=7)
    b = generate_daily_metrics(date(2026, 1, 1), days=30, seed=8)
    assert [m.resting_hr_bpm for m in a] != [m.resting_hr_bpm for m in b]


def test_generates_the_requested_number_of_consecutive_days():
    metrics = generate_daily_metrics(date(2026, 1, 1), days=45)
    assert len(metrics) == 45
    assert metrics[0].date == date(2026, 1, 1)
    assert metrics[-1].date == date(2026, 2, 14)


def test_values_are_physiologically_plausible():
    """Missing days are the normal case for a wearable; only present values are checked."""
    for m in generate_daily_metrics(date(2026, 1, 1), days=200):
        if m.resting_hr_bpm is not None:
            assert 40 <= m.resting_hr_bpm <= 100
        if m.hrv_rmssd_ms is not None:
            assert 5 <= m.hrv_rmssd_ms <= 150
        if m.steps is not None:
            assert 0 <= m.steps <= 40000
        if m.sleep_efficiency_pct is not None:
            assert 0 <= m.sleep_efficiency_pct <= 100
        if m.sleep_midpoint_local_min is not None:
            assert 0 <= m.sleep_midpoint_local_min < 1440


def test_generator_leaves_realistic_gaps():
    """A real wearable is not worn every night; the demo must exercise gap handling."""
    metrics = generate_daily_metrics(date(2026, 1, 1), days=300)
    assert any(m.hrv_rmssd_ms is None for m in metrics)
    assert any(m.steps is not None for m in metrics)


def test_weekends_differ_from_weekdays():
    metrics = generate_daily_metrics(date(2026, 1, 1), days=200)
    weekday = [m.steps for m in metrics if m.date.weekday() < 5 and m.steps]
    weekend = [m.steps for m in metrics if m.date.weekday() >= 5 and m.steps]
    assert sum(weekday) / len(weekday) != pytest.approx(sum(weekend) / len(weekend), rel=0.01)


def test_seed_demo_populates_profile_metrics_and_scores(db):
    weeks = seed_demo(db, days=200)
    db.flush()
    assert db.query(Profile).count() == 1
    assert db.query(DailyMetric).count() == 200
    assert db.query(BioAgeScore).count() == weeks
    assert weeks > 20


def test_seed_demo_scores_have_valid_bands(db):
    seed_demo(db, days=200)
    db.flush()
    for score in db.query(BioAgeScore).all():
        assert score.ci_low < score.composite_age < score.ci_high
        assert 18.0 <= score.composite_age <= 100.0


def test_seed_demo_is_rerunnable(db):
    seed_demo(db, days=120)
    db.flush()
    first = db.query(DailyMetric).count()
    seed_demo(db, days=120)
    db.flush()
    assert db.query(DailyMetric).count() == first
