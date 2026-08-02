from datetime import date, timedelta

import pytest

from bioage.db.models import BioAgeScore, DailyMetric, Measurement, Profile
from bioage.scoring import iso_week_starts, rescore_all, score_week
from bioage.types import Sex


@pytest.fixture
def populated(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 1, 1)))
    db.add(Measurement(kind="height_m", value=1.78, measured_on=date(2026, 1, 1)))
    db.add(Measurement(kind="weight_kg", value=74.0, measured_on=date(2026, 1, 1)))
    db.add(Measurement(kind="waist_cm", value=88.0, measured_on=date(2026, 1, 1)))
    start = date(2026, 4, 1)
    for i in range(90):
        db.add(DailyMetric(
            date=start + timedelta(days=i),
            resting_hr_bpm=60.0,
            hrv_rmssd_ms=45.0,
            steps=9000,
            active_zone_minutes=25,
            sleep_efficiency_pct=90.0,
            sleep_midpoint_local_min=180.0,
        ))
    db.flush()
    return db


def test_iso_week_starts_are_mondays():
    weeks = iso_week_starts(date(2026, 4, 1), date(2026, 5, 1))
    assert all(w.weekday() == 0 for w in weeks)


def test_iso_week_starts_are_contiguous_and_ordered():
    weeks = iso_week_starts(date(2026, 4, 1), date(2026, 6, 1))
    assert weeks == sorted(weeks)
    for a, b in zip(weeks, weeks[1:], strict=False):
        assert (b - a).days == 7


def test_score_week_produces_a_composite_with_a_band(populated):
    score = score_week(populated, week_start=date(2026, 6, 1))
    assert score is not None
    assert score.ci_low < score.composite_age < score.ci_high
    assert score.chronological_age > 30


def test_score_week_records_its_components_and_coverage(populated):
    score = score_week(populated, week_start=date(2026, 6, 1))
    assert score is not None
    names = {c["component"] for c in score.components}
    assert "kdm" in names
    assert "ntnu_fitness" in names
    assert score.coverage["total_days"] > 0


def test_score_week_returns_none_before_any_data(populated):
    assert score_week(populated, week_start=date(2026, 1, 5)) is None


def test_thin_window_is_flagged_low_confidence_with_a_wider_band(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 1, 1)))
    db.add(Measurement(kind="height_m", value=1.78, measured_on=date(2026, 1, 1)))
    db.add(Measurement(kind="weight_kg", value=74.0, measured_on=date(2026, 1, 1)))
    db.add(Measurement(kind="waist_cm", value=88.0, measured_on=date(2026, 1, 1)))
    start = date(2026, 6, 1)
    for i in range(16):
        db.add(DailyMetric(
            date=start + timedelta(days=i), resting_hr_bpm=60.0, hrv_rmssd_ms=45.0,
            steps=9000, sleep_efficiency_pct=90.0, sleep_midpoint_local_min=180.0,
        ))
    db.flush()
    score = score_week(db, week_start=date(2026, 6, 22))
    assert score is not None
    assert score.is_low_confidence is True


def test_rescore_all_is_idempotent(populated):
    first = rescore_all(populated)
    populated.flush()
    rows_after_first = populated.query(BioAgeScore).count()
    second = rescore_all(populated)
    populated.flush()
    assert first == second
    assert populated.query(BioAgeScore).count() == rows_after_first


def test_rescore_all_overwrites_rather_than_duplicating(populated):
    rescore_all(populated)
    populated.flush()
    before = populated.query(BioAgeScore).order_by(BioAgeScore.week_start).first()
    before_week, before_age = before.week_start, before.composite_age
    populated.query(DailyMetric).update({DailyMetric.resting_hr_bpm: 80.0})
    populated.flush()
    rescore_all(populated)
    populated.flush()
    after = populated.query(BioAgeScore).order_by(BioAgeScore.week_start).first()
    assert after.week_start == before_week
    assert after.composite_age != pytest.approx(before_age)


def test_a_healthier_profile_scores_younger(db):
    def build(rhr: float, steps: int, rmssd: float) -> float:
        db.query(DailyMetric).delete()
        db.query(BioAgeScore).delete()
        db.merge(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 1, 1)))
        measurements = (("height_m", 1.78), ("weight_kg", 74.0), ("waist_cm", 88.0))
        for index, (kind, value) in enumerate(measurements, start=1):
            db.merge(Measurement(id=index, kind=kind, value=value,
                                 measured_on=date(2026, 1, 1)))
        for i in range(60):
            db.add(DailyMetric(
                date=date(2026, 4, 1) + timedelta(days=i), resting_hr_bpm=rhr,
                hrv_rmssd_ms=rmssd, steps=steps, sleep_efficiency_pct=90.0,
                sleep_midpoint_local_min=180.0,
            ))
        db.flush()
        score = score_week(db, week_start=date(2026, 5, 25))
        assert score is not None
        return score.composite_age

    fit = build(rhr=52.0, steps=13000, rmssd=65.0)
    unfit = build(rhr=78.0, steps=2500, rmssd=22.0)
    assert fit < unfit
