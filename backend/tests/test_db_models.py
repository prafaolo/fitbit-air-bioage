from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from bioage.db.models import (
    BioAgeScore,
    DailyMetric,
    Measurement,
    Profile,
    RawDataPoint,
    SyncState,
)
from bioage.types import Sex


def test_raw_data_point_round_trips_jsonb(db):
    db.add(RawDataPoint(
        data_type="daily-resting-heart-rate",
        point_date=date(2026, 6, 1),
        payload={"dailyRestingHeartRate": {"beatsPerMinute": "58"}},
    ))
    db.flush()
    stored = db.query(RawDataPoint).one()
    assert stored.payload["dailyRestingHeartRate"]["beatsPerMinute"] == "58"


def test_raw_data_point_rejects_duplicate_type_and_date(db):
    for _ in range(2):
        db.add(RawDataPoint(
            data_type="steps", point_date=date(2026, 6, 1), payload={},
        ))
    with pytest.raises(IntegrityError):
        db.flush()


def test_daily_metric_allows_every_measurement_to_be_null(db):
    db.add(DailyMetric(date=date(2026, 6, 1)))
    db.flush()
    stored = db.query(DailyMetric).one()
    assert stored.resting_hr_bpm is None
    assert stored.steps is None


def test_profile_stores_sex_as_enum_value(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 3, 14)))
    db.flush()
    assert db.query(Profile).one().sex is Sex.MALE


def test_measurements_are_dated_and_multiple_per_kind(db):
    db.add_all([
        Measurement(kind="waist_cm", value=88.0, measured_on=date(2026, 5, 1)),
        Measurement(kind="waist_cm", value=86.0, measured_on=date(2026, 7, 1)),
    ])
    db.flush()
    assert db.query(Measurement).count() == 2


def test_bioage_score_stores_components_as_jsonb(db):
    db.add(BioAgeScore(
        week_start=date(2026, 6, 1),
        chronological_age=36.2,
        composite_age=33.8,
        ci_low=28.1,
        ci_high=39.5,
        components=[{"component": "kdm", "age_years": 34.0}],
        coverage={"rhr_days": 27},
        is_low_confidence=False,
        computed_at=datetime.now(UTC),
    ))
    db.flush()
    assert db.query(BioAgeScore).one().components[0]["component"] == "kdm"


def test_sync_state_is_keyed_by_data_type(db):
    db.add(SyncState(data_type="steps", synced_through=date(2026, 7, 1)))
    db.flush()
    assert db.query(SyncState).one().data_type == "steps"
