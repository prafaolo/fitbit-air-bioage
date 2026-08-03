"""Demo/real data provenance: eviction on real sync, and the inverse seeding guard.

`seed_demo` writes synthetic rows straight into the same tables real data lands in, with
nothing distinguishing them -- see docs/SETUP.md step 2 and bioage.demo.generator. These
tests cover both directions of the resulting corruption risk:

* A real sync must evict every `is_demo=True` row, across all four tables, before it
  writes anything -- including the demo Profile, so a user who never opens the Profile
  page does not silently keep scoring against birthdate 1990-03-14.
* `seed_demo` must refuse to run against a database that already holds real data, unless
  explicitly forced.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from bioage.db.models import BioAgeScore, DailyMetric, Measurement, Profile, RawDataPoint
from bioage.demo.generator import DEMO_BIRTHDATE, RealDataExistsError, seed_demo
from bioage.ingest.sync import SyncService, evict_demo_data
from bioage.profile import resolve_profile
from bioage.scoring import rescore_all
from bioage.types import Sex

# A date range chosen to be nowhere near "today" (whatever day the suite happens to run
# on): seed_demo anchors its synthetic history to date.today(), so real data used to
# prove eviction must live somewhere that range can never reach.
REAL_START = date(2024, 1, 1)
REAL_DAYS = [REAL_START + timedelta(days=i) for i in range(40)]
REAL_END_EXCLUSIVE = REAL_DAYS[-1] + timedelta(days=1)


class RealDataClient:
    """A minimal stand-in for the Google Health client, serving a controlled real
    history across resting HR, HRV, steps and sleep -- enough data types for the
    composite estimator's min_components floor -- for a fixed set of days."""

    def __init__(self, days: list[date] = REAL_DAYS):
        self.days = days

    def list_data_points(self, spec, window):
        builder = {
            "daily-resting-heart-rate": self._rhr,
            "daily-heart-rate-variability": self._hrv,
            "steps": self._steps,
            "sleep": self._sleep,
        }.get(spec.data_type_id)
        if builder is None:
            return []
        return [builder(d) for d in self.days if window.start <= d < window.end]

    @staticmethod
    def _proto_date(day: date) -> dict:
        return {"year": day.year, "month": day.month, "day": day.day}

    def _rhr(self, day: date) -> dict:
        return {
            "dailyRestingHeartRate": {
                "date": self._proto_date(day),
                "beatsPerMinute": str(58 + day.day % 5),
            }
        }

    def _hrv(self, day: date) -> dict:
        return {
            "dailyHeartRateVariability": {
                "date": self._proto_date(day),
                "averageHeartRateVariabilityMilliseconds": 42.0,
                "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds": 44.0
                + day.day % 7,
            }
        }

    def _steps(self, day: date) -> dict:
        return {
            "steps": {
                "interval": {
                    "startTime": f"{day.isoformat()}T00:00:00Z",
                    "endTime": f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z",
                },
                "count": str(8000 + day.day * 100),
            }
        }

    def _sleep(self, day: date) -> dict:
        previous = day - timedelta(days=1)
        return {
            "sleep": {
                "type": "STAGES",
                "interval": {
                    "startTime": f"{previous.isoformat()}T23:00:00Z",
                    "endTime": f"{day.isoformat()}T07:00:00Z",
                    "startUtcOffset": "0s",
                    "endUtcOffset": "0s",
                },
                "metadata": {"mainSleep": True, "processed": True, "stagesStatus": "SUCCEEDED"},
                "summary": {
                    "minutesAsleep": "440",
                    "minutesAwake": "20",
                    "minutesInSleepPeriod": "480",
                    "minutesToFallAsleep": "0",
                    "minutesAfterWakeUp": "0",
                    "stagesSummary": [
                        {"type": "AWAKE", "count": "1", "minutes": "20"},
                        {"type": "LIGHT", "count": "1", "minutes": "240"},
                        {"type": "DEEP", "count": "1", "minutes": "90"},
                        {"type": "REM", "count": "1", "minutes": "110"},
                    ],
                },
            }
        }


def _add_real_profile(db) -> None:
    """Simulate the user visiting the Profile page after their demo profile was
    evicted -- resolve_profile needs one before rescore_all can produce anything."""
    db.merge(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 1, 1)))
    for index, (kind, value) in enumerate(
        (("height_m", 1.8), ("weight_kg", 75.0), ("waist_cm", 85.0)), start=1
    ):
        db.merge(Measurement(id=index, kind=kind, value=value, measured_on=REAL_START))
    db.flush()


# --- 1. Seed demo, then a real sync must leave zero demo rows and only real data. -----


def test_real_sync_evicts_all_demo_rows_before_writing(db):
    seed_demo(db, days=60)
    db.flush()
    assert db.query(DailyMetric).filter_by(is_demo=True).count() > 0
    assert db.query(BioAgeScore).filter_by(is_demo=True).count() > 0
    assert db.query(Measurement).filter_by(is_demo=True).count() > 0
    assert db.query(Profile).filter_by(is_demo=True).count() == 1

    SyncService(db, RealDataClient(), backfill_days=len(REAL_DAYS) + 5).sync_all(
        today=REAL_END_EXCLUSIVE
    )
    db.flush()

    # Zero is_demo=True rows remain, in any of the four tagged tables.
    assert db.query(DailyMetric).filter_by(is_demo=True).count() == 0
    assert db.query(BioAgeScore).filter_by(is_demo=True).count() == 0
    assert db.query(Measurement).filter_by(is_demo=True).count() == 0
    assert db.query(Profile).filter_by(is_demo=True).count() == 0

    # The real data is present...
    real_dates = {m.date for m in db.query(DailyMetric).all()}
    assert real_dates == set(REAL_DAYS)

    # ...and rescoring now (once a real profile exists) covers only the real range, not
    # the year of demo history that was just evicted.
    _add_real_profile(db)
    weeks = rescore_all(db)
    db.flush()
    assert weeks > 0
    scores = db.query(BioAgeScore).all()
    assert scores
    assert all(REAL_START <= s.week_start <= REAL_END_EXCLUSIVE for s in scores)
    assert all(not s.is_demo for s in scores)


def test_real_sync_clears_the_demo_profile_and_resolve_profile_returns_none(db):
    seed_demo(db, days=60)
    db.flush()
    assert resolve_profile(db, as_of=date.today()) is not None

    SyncService(db, RealDataClient(), backfill_days=len(REAL_DAYS) + 5).sync_all(
        today=REAL_END_EXCLUSIVE
    )
    db.flush()

    assert db.query(Profile).count() == 0
    resolved = resolve_profile(db, as_of=REAL_END_EXCLUSIVE)
    assert resolved is None
    # In particular, nothing is silently scored against the fake demo birthdate.
    assert db.get(Profile, 1) is None


def test_evict_demo_data_is_a_noop_and_logs_nothing_when_there_is_no_demo_data(db, caplog):
    import logging

    _add_real_profile(db)
    db.add(DailyMetric(date=REAL_START, resting_hr_bpm=60.0))
    db.flush()

    with caplog.at_level(logging.INFO):
        removed = evict_demo_data(db)
    assert removed == 0
    assert not caplog.records
    assert db.query(DailyMetric).count() == 1


# --- 2. seed_demo marks every row it writes, across all four tables. ------------------


def test_seed_demo_marks_every_row_it_writes_as_demo(db):
    seed_demo(db, days=120)
    db.flush()

    assert db.query(Profile).filter_by(is_demo=False).count() == 0
    assert db.query(Profile).filter_by(is_demo=True).count() == 1
    assert db.query(Measurement).filter_by(is_demo=False).count() == 0
    assert db.query(Measurement).filter_by(is_demo=True).count() == 3
    assert db.query(DailyMetric).filter_by(is_demo=False).count() == 0
    assert db.query(DailyMetric).filter_by(is_demo=True).count() == 120
    assert db.query(BioAgeScore).count() > 0
    assert db.query(BioAgeScore).filter_by(is_demo=False).count() == 0
    assert db.query(Profile).one().birthdate == DEMO_BIRTHDATE


# --- 3. seed_demo refuses when real data exists; --force overrides. -------------------


def test_seed_demo_refuses_when_daily_metrics_hold_real_data(db):
    db.add(DailyMetric(date=REAL_START, resting_hr_bpm=60.0))
    db.flush()

    with pytest.raises(RealDataExistsError):
        seed_demo(db, days=30)

    # Refusal must not have written anything.
    assert db.query(Profile).count() == 0
    assert db.query(DailyMetric).filter_by(is_demo=True).count() == 0


def test_seed_demo_refuses_when_raw_data_points_hold_real_data(db):
    db.add(
        RawDataPoint(
            data_type="daily-resting-heart-rate",
            point_date=REAL_START,
            payload_hash="real-hash",
            payload={"dailyRestingHeartRate": {"beatsPerMinute": "55"}},
        )
    )
    db.flush()

    with pytest.raises(RealDataExistsError):
        seed_demo(db, days=30)


def test_seed_demo_force_overrides_the_refusal(db):
    db.add(DailyMetric(date=REAL_START, resting_hr_bpm=60.0))
    db.flush()

    weeks = seed_demo(db, days=30, force=True)
    db.flush()

    assert weeks >= 0
    assert db.query(Profile).filter_by(is_demo=True).count() == 1
    # The pre-existing real row is untouched; seed_demo does not delete anything.
    real_row = db.get(DailyMetric, REAL_START)
    assert real_row is not None
    assert real_row.is_demo is False


def test_seed_demo_is_not_blocked_by_its_own_earlier_demo_rows(db):
    """A rerun (SETUP.md step 2's normal path) must not be mistaken for real data."""
    seed_demo(db, days=30)
    db.flush()
    seed_demo(db, days=30)  # must not raise
    db.flush()
    assert db.query(DailyMetric).filter_by(is_demo=True).count() == 30


# --- 4. `bioage rebuild` re-derives from raw_data_points, which is always real. -------


def test_rebuild_produces_is_demo_false_rows(db):
    from bioage.ingest.sync import normalize_all

    seed_demo(db, days=60)
    db.flush()
    assert db.query(DailyMetric).filter_by(is_demo=True).count() > 0

    db.add(
        RawDataPoint(
            data_type="daily-resting-heart-rate",
            point_date=REAL_START,
            payload_hash="rebuildtest",
            payload={
                "dailyRestingHeartRate": {
                    "date": {"year": REAL_START.year, "month": REAL_START.month,
                              "day": REAL_START.day},
                    "beatsPerMinute": "55",
                }
            },
        )
    )
    db.flush()

    db.query(BioAgeScore).delete()
    db.query(DailyMetric).delete()
    db.flush()
    normalize_all(db)
    db.flush()

    remaining = db.query(DailyMetric).all()
    assert len(remaining) == 1
    assert remaining[0].date == REAL_START
    assert remaining[0].is_demo is False
