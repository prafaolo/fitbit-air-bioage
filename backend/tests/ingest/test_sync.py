import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from bioage.db.models import DailyMetric, RawDataPoint, SyncState
from bioage.ingest.registry import get_spec
from bioage.ingest.sync import SyncService, normalize_all

FIXTURES = Path(__file__).parent.parent / "fixtures" / "googlehealth"


class FakeClient:
    """Returns the fixture payload for each data type and records the windows requested."""

    def __init__(self, payloads: dict[str, list[dict]] | None = None):
        self.payloads = payloads or {}
        self.requested: list[tuple[str, date, date]] = []

    def list_data_points(self, spec, window):
        self.requested.append((spec.data_type_id, window.start, window.end))
        return self.payloads.get(spec.data_type_id, [])


def fixture_points(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"{name}.json").read_text())["dataPoints"]


@pytest.fixture
def client() -> FakeClient:
    return FakeClient({
        "daily-resting-heart-rate": fixture_points("daily_resting_heart_rate"),
        "daily-heart-rate-variability": fixture_points("daily_heart_rate_variability"),
        "steps": fixture_points("steps"),
        "sleep": fixture_points("sleep"),
    })


def test_sync_stores_raw_payloads_before_parsing(db, client):
    SyncService(db, client, backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    assert db.query(RawDataPoint).count() == 2


def test_sync_writes_normalized_daily_metrics(db, client):
    SyncService(db, client, backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    metric = db.get(DailyMetric, date(2026, 6, 1))
    assert metric is not None
    assert metric.resting_hr_bpm == pytest.approx(58.0)


def test_sync_merges_data_types_into_one_daily_row(db, client):
    service = SyncService(db, client, backfill_days=30)
    service.sync_data_type(get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10))
    service.sync_data_type(get_spec("daily-heart-rate-variability"), today=date(2026, 6, 10))
    db.flush()
    metric = db.get(DailyMetric, date(2026, 6, 1))
    assert metric.resting_hr_bpm == pytest.approx(58.0)
    assert metric.hrv_rmssd_ms == pytest.approx(46.7)


def test_first_sync_backfills_the_configured_window(db, client):
    SyncService(db, client, backfill_days=45).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    requested_start = client.requested[0][1]
    assert requested_start == date(2026, 6, 10) - timedelta(days=45)


def test_subsequent_sync_resumes_from_the_watermark(db, client):
    db.add(SyncState(data_type="daily-resting-heart-rate", synced_through=date(2026, 6, 5)))
    db.flush()
    SyncService(db, client, backfill_days=90).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    assert client.requested[0][1] == date(2026, 6, 5)


def test_watermark_advances_after_a_successful_sync(db, client):
    SyncService(db, client, backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    assert db.get(SyncState, "daily-resting-heart-rate").synced_through == date(2026, 6, 10)


def test_watermark_does_not_advance_when_the_fetch_fails(db):
    class Failing:
        def list_data_points(self, spec, window):
            raise RuntimeError("boom")

    report = SyncService(db, Failing(), backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    assert report.error is not None
    assert db.get(SyncState, "daily-resting-heart-rate").synced_through is None


def test_one_failing_data_type_does_not_abort_the_others(db, client):
    failing_type = "daily-heart-rate-variability"

    class PartiallyFailingClient:
        """Raises for one data type, delegates to the real fixture client for the rest."""

        def list_data_points(self, spec, window):
            if spec.data_type_id == failing_type:
                raise RuntimeError("boom")
            return client.list_data_points(spec, window)

    reports = SyncService(db, PartiallyFailingClient(), backfill_days=30).sync_all(
        today=date(2026, 6, 10)
    )
    db.flush()
    by_type = {r.data_type: r for r in reports}

    assert by_type[failing_type].error is not None
    assert db.get(SyncState, failing_type).synced_through is None

    healthy_type = "daily-resting-heart-rate"
    assert by_type[healthy_type].points_fetched > 0
    assert db.get(SyncState, healthy_type).synced_through == date(2026, 6, 10)


def test_parse_failure_is_recorded_and_does_not_abort_the_sync(db):
    malformed = {
        "dailyRestingHeartRate": {
            "date": {"year": 2026, "month": 13, "day": 99},
            "beatsPerMinute": "58",
        }
    }
    well_formed = fixture_points("daily_resting_heart_rate")[1]  # 2026-06-02, 61 bpm

    class MalformedClient:
        def list_data_points(self, spec, window):
            return [malformed, well_formed]

    report = SyncService(db, MalformedClient(), backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()

    assert report.error is None
    assert report.parse_errors == 1
    assert report.points_fetched == 2
    # Both payloads were still stored raw...
    assert db.query(RawDataPoint).count() == 2
    # ...the well-formed payload in the same window was still normalized...
    assert db.get(DailyMetric, date(2026, 6, 2)).resting_hr_bpm == pytest.approx(61.0)
    # ...and the watermark still advances: the malformed payload is durably stored, so a
    # future parser fix reaches it via normalize_all rather than a re-fetch.
    assert db.get(SyncState, "daily-resting-heart-rate").synced_through == date(2026, 6, 10)


def test_an_unexpected_error_in_one_type_does_not_discard_earlier_reports(db, client, monkeypatch):
    """Exercises sync_all's own per-item guard specifically.

    The fetch-level try/except inside sync_data_type already contains fetch failures
    before they ever reach sync_all's loop, so a raising client (as used in
    test_one_failing_data_type_does_not_abort_the_others) does not exercise sync_all's
    guard at all. To reach it, the failure has to escape sync_data_type through a path
    neither inner guard covers -- here, the per-payload write step -- standing in for
    an unanticipated failure such as a database error.
    """
    import bioage.ingest.sync as sync_module

    real_upsert_daily = sync_module._upsert_daily

    def flaky_upsert_daily(session, day, values):
        if "hrv_rmssd_ms" in values:
            raise RuntimeError("unexpected write failure")
        return real_upsert_daily(session, day, values)

    monkeypatch.setattr(sync_module, "_upsert_daily", flaky_upsert_daily)

    # daily-resting-heart-rate precedes daily-heart-rate-variability in DATA_TYPES, so a
    # successful report for it is already in hand by the time the flaky type raises.
    reports = SyncService(db, client, backfill_days=30).sync_all(today=date(2026, 6, 10))
    db.flush()
    by_type = {r.data_type: r for r in reports}

    assert by_type["daily-heart-rate-variability"].error is not None
    healthy = by_type["daily-resting-heart-rate"]
    assert healthy.error is None
    assert healthy.points_fetched > 0


def test_resync_is_idempotent(db, client):
    service = SyncService(db, client, backfill_days=30)
    service.sync_data_type(get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10))
    db.flush()
    first = db.query(RawDataPoint).count()
    db.query(SyncState).delete()
    service.sync_data_type(get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10))
    db.flush()
    assert db.query(RawDataPoint).count() == first


def test_normalize_all_reparses_stored_raw_without_refetching(db, client):
    SyncService(db, client, backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    db.query(DailyMetric).delete()
    db.flush()
    written = normalize_all(db)
    db.flush()
    assert written > 0
    assert db.get(DailyMetric, date(2026, 6, 1)).resting_hr_bpm == pytest.approx(58.0)


def test_expected_empty_types_report_zero_without_error(db):
    report = SyncService(db, FakeClient(), backfill_days=30).sync_data_type(
        get_spec("daily-vo2-max"), today=date(2026, 6, 10)
    )
    assert report.error is None
    assert report.points_fetched == 0
