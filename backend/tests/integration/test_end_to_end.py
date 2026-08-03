"""Sync -> normalize -> score -> serve, against a mocked Google Health API."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bioage.api.app import create_app
from bioage.api.deps import get_session
from bioage.db.models import BioAgeScore, DailyMetric, Measurement, Profile, RawDataPoint
from bioage.ingest.sync import SyncService, normalize_all
from bioage.types import Sex

FIXTURES = Path(__file__).parent.parent / "fixtures" / "googlehealth"


class ScriptedApi:
    """Serves a synthetic 120-day history in the documented payload shapes."""

    def __init__(self, end: date, days: int = 120):
        self.end = end
        self.days = days

    def list_data_points(self, spec, window):
        builders = {
            "daily-resting-heart-rate": self._rhr,
            "daily-heart-rate-variability": self._hrv,
            "steps": self._steps,
            "sleep": self._sleep,
        }
        builder = builders.get(spec.data_type_id)
        if builder is None:
            return []
        return [
            builder(self.end - timedelta(days=i))
            for i in range(self.days)
            if window.start <= self.end - timedelta(days=i) < window.end
        ]

    @staticmethod
    def _proto_date(day: date) -> dict:
        return {"year": day.year, "month": day.month, "day": day.day}

    def _rhr(self, day: date) -> dict:
        return {"dailyRestingHeartRate": {
            "date": self._proto_date(day), "beatsPerMinute": str(58 + day.day % 5)
        }}

    def _hrv(self, day: date) -> dict:
        return {"dailyHeartRateVariability": {
            "date": self._proto_date(day),
            "averageHeartRateVariabilityMilliseconds": 42.0,
            "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds": 44.0 + day.day % 7,
        }}

    def _steps(self, day: date) -> dict:
        return {"steps": {
            "interval": {
                "startTime": f"{day.isoformat()}T00:00:00Z",
                "endTime": f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z",
            },
            "count": str(8000 + day.day * 100),
        }}

    def _sleep(self, day: date) -> dict:
        previous = day - timedelta(days=1)
        return {"sleep": {
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
        }}


@pytest.fixture
def profiled(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 3, 14)))
    db.add_all([
        Measurement(kind="height_m", value=1.78, measured_on=date(2026, 1, 1)),
        Measurement(kind="weight_kg", value=74.5, measured_on=date(2026, 1, 1)),
        Measurement(kind="waist_cm", value=87.0, measured_on=date(2026, 1, 1)),
    ])
    db.flush()
    return db


def test_full_pipeline_from_api_payloads_to_served_series(profiled):
    today = date(2026, 7, 1)
    service = SyncService(profiled, ScriptedApi(end=today), backfill_days=120)
    reports = service.sync_all(today=today)
    profiled.flush()

    assert not [r for r in reports if r.error]
    assert profiled.query(RawDataPoint).count() > 300
    assert profiled.query(DailyMetric).count() > 100

    from bioage.scoring import rescore_all
    weeks = rescore_all(profiled)
    profiled.flush()
    assert weeks > 10

    app = create_app()
    app.dependency_overrides[get_session] = lambda: profiled
    points = TestClient(app).get("/api/bioage/series").json()
    assert len(points) == weeks
    for point in points:
        assert point["ci_low"] < point["composite_age"] < point["ci_high"]
        assert 18.0 <= point["composite_age"] <= 100.0


def test_sleep_derivations_survive_the_whole_pipeline(profiled):
    today = date(2026, 7, 1)
    SyncService(profiled, ScriptedApi(end=today), backfill_days=60).sync_all(today=today)
    profiled.flush()
    metric = profiled.query(DailyMetric).filter(
        DailyMetric.sleep_efficiency_pct.isnot(None)
    ).first()
    assert metric is not None
    # minutesAsleep=440 of minutesInSleepPeriod=480
    assert metric.sleep_efficiency_pct == pytest.approx(440 / 480 * 100, abs=0.1)
    assert metric.waso_min == pytest.approx(20.0, abs=0.1)


def test_reparsing_raw_data_reproduces_identical_daily_metrics(profiled):
    today = date(2026, 7, 1)
    SyncService(profiled, ScriptedApi(end=today), backfill_days=60).sync_all(today=today)
    profiled.flush()
    before = {
        m.date: (m.resting_hr_bpm, m.hrv_rmssd_ms, m.steps)
        for m in profiled.query(DailyMetric).all()
    }
    profiled.query(DailyMetric).delete()
    profiled.flush()
    normalize_all(profiled)
    profiled.flush()
    after = {
        m.date: (m.resting_hr_bpm, m.hrv_rmssd_ms, m.steps)
        for m in profiled.query(DailyMetric).all()
    }
    assert after == before


def test_running_the_whole_pipeline_twice_changes_nothing(profiled):
    today = date(2026, 7, 1)
    from bioage.scoring import rescore_all

    api = ScriptedApi(end=today)
    SyncService(profiled, api, backfill_days=120).sync_all(today=today)
    rescore_all(profiled)
    profiled.flush()
    first = {s.week_start: s.composite_age for s in profiled.query(BioAgeScore).all()}

    SyncService(profiled, api, backfill_days=120).sync_all(today=today)
    rescore_all(profiled)
    profiled.flush()
    second = {s.week_start: s.composite_age for s in profiled.query(BioAgeScore).all()}

    assert first.keys() == second.keys()
    for week in first:
        assert first[week] == pytest.approx(second[week])


def test_changing_the_waist_measurement_only_affects_later_weeks(profiled):
    today = date(2026, 7, 1)
    from bioage.scoring import rescore_all

    SyncService(profiled, ScriptedApi(end=today), backfill_days=120).sync_all(today=today)
    rescore_all(profiled)
    profiled.flush()
    before = {s.week_start: s.composite_age for s in profiled.query(BioAgeScore).all()}

    profiled.add(Measurement(kind="waist_cm", value=79.0, measured_on=date(2026, 6, 1)))
    profiled.flush()
    rescore_all(profiled)
    profiled.flush()
    after = {s.week_start: s.composite_age for s in profiled.query(BioAgeScore).all()}

    early = [w for w in before if w < date(2026, 5, 1)]
    late = [w for w in before if w > date(2026, 6, 8)]
    assert early and late
    for week in early:
        assert after[week] == pytest.approx(before[week]), "past weeks must not be rewritten"
    assert any(after[w] != pytest.approx(before[w]) for w in late)
