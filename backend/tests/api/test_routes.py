from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from bioage.api.app import create_app
from bioage.api.deps import get_session
from bioage.api.routes_auth import oauth_state_store
from bioage.api.routes_sync import get_sync_session_cm
from bioage.config import Settings
from bioage.db.models import OAuthCredential, SyncRun
from bioage.demo.generator import seed_demo
from bioage.ingest.client import BASE_URL as HEALTH_API_BASE_URL
from bioage.ingest.registry import DATA_TYPES

TOKEN_URL = "https://oauth2.googleapis.com/token"


@pytest.fixture
def client(db):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    # The background sync job cannot use the request's own session (FastAPI closes it
    # as soon as the endpoint returns, before background tasks run) -- production opens
    # a brand-new one, but tests need the background task to observe and mutate the
    # same transactional `db` fixture session the test itself asserts against, or data
    # the test only flush()ed (never committed) into the outer test transaction would
    # be invisible to a background task on its own connection. See routes_sync.py.
    app.dependency_overrides[get_sync_session_cm] = lambda: (lambda: nullcontext(db))
    return TestClient(app)


@pytest.fixture
def seeded_client(client, db):
    seed_demo(db, days=200)
    db.flush()
    return client


def test_health_endpoint_reports_ok(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_series_is_empty_before_any_data(client):
    response = client.get("/api/bioage/series")
    assert response.status_code == 200
    assert response.json() == []


def test_series_returns_one_point_per_week_in_ascending_order(seeded_client):
    points = seeded_client.get("/api/bioage/series").json()
    assert len(points) > 20
    weeks = [p["week_start"] for p in points]
    assert weeks == sorted(weeks)


def test_every_series_point_carries_a_confidence_band(seeded_client):
    for point in seeded_client.get("/api/bioage/series").json():
        assert point["ci_low"] < point["composite_age"] < point["ci_high"]
        assert "chronological_age" in point


def test_series_respects_the_date_filters(seeded_client):
    all_points = seeded_client.get("/api/bioage/series").json()
    cutoff = all_points[len(all_points) // 2]["week_start"]
    filtered = seeded_client.get(f"/api/bioage/series?from_date={cutoff}").json()
    assert all(p["week_start"] >= cutoff for p in filtered)
    assert len(filtered) < len(all_points)


def test_week_detail_includes_components_and_coverage(seeded_client):
    week = seeded_client.get("/api/bioage/series").json()[-1]["week_start"]
    detail = seeded_client.get(f"/api/bioage/weeks/{week}").json()
    assert {c["component"] for c in detail["components"]}
    assert "total_days" in detail["coverage"]


def test_week_detail_404s_for_an_unscored_week(seeded_client):
    assert seeded_client.get("/api/bioage/weeks/1999-01-04").status_code == 404


def test_profile_404s_when_unset(client):
    assert client.get("/api/profile").status_code == 404


def test_profile_can_be_created_and_read_back(client):
    response = client.put("/api/profile", json={"sex": "female", "birthdate": "1988-02-29"})
    assert response.status_code == 200
    body = client.get("/api/profile").json()
    assert body["sex"] == "female"
    assert body["birthdate"] == "1988-02-29"


def test_profile_rejects_an_invalid_sex(client):
    assert (
        client.put(
            "/api/profile", json={"sex": "unknown", "birthdate": "1988-02-29"}
        ).status_code
        == 422
    )


def test_profile_rejects_a_future_birthdate(client):
    assert (
        client.put(
            "/api/profile", json={"sex": "male", "birthdate": "2099-01-01"}
        ).status_code
        == 422
    )


def test_measurements_can_be_added_and_listed(client):
    client.put("/api/profile", json={"sex": "male", "birthdate": "1990-01-01"})
    created = client.post(
        "/api/profile/measurements",
        json={"kind": "waist_cm", "value": 88.0, "measured_on": "2026-06-01"},
    )
    assert created.status_code == 201
    measurements = client.get("/api/profile").json()["measurements"]
    assert measurements[0]["kind"] == "waist_cm"


def test_measurement_rejects_an_unknown_kind(client):
    assert (
        client.post(
            "/api/profile/measurements",
            json={"kind": "shoe_size", "value": 44.0, "measured_on": "2026-06-01"},
        ).status_code
        == 422
    )


def test_measurement_rejects_a_non_positive_value(client):
    assert (
        client.post(
            "/api/profile/measurements",
            json={"kind": "waist_cm", "value": 0.0, "measured_on": "2026-06-01"},
        ).status_code
        == 422
    )


def test_measurement_can_be_deleted(client):
    client.put("/api/profile", json={"sex": "male", "birthdate": "1990-01-01"})
    created = client.post(
        "/api/profile/measurements",
        json={"kind": "waist_cm", "value": 88.0, "measured_on": "2026-06-01"},
    ).json()
    assert client.delete(f"/api/profile/measurements/{created['id']}").status_code == 204
    assert client.get("/api/profile").json()["measurements"] == []


def test_sync_status_reports_disconnected_before_oauth(client):
    body = client.get("/api/sync/status").json()
    assert body["connected"] is False
    assert any(d["data_type"] == "steps" for d in body["data_types"])
    assert body["sync"]["running"] is False


def test_sync_status_lists_vo2max_as_expected_empty(client):
    body = client.get("/api/sync/status").json()
    vo2 = next(d for d in body["data_types"] if d["data_type"] == "daily-vo2-max")
    assert vo2["expected_empty"] is True


def test_sync_status_reports_real_points_stored_for_an_expected_empty_type(client, db):
    """points_stored must reflect the raw archive, not be structurally pinned at 0 --
    otherwise the coverage table's "expected empty" copy would be a hardcoded answer,
    not an observation, even if Google started populating this data type tomorrow."""
    from bioage.db.models import RawDataPoint

    db.add(RawDataPoint(
        data_type="daily-vo2-max",
        point_date=date(2026, 6, 1),
        payload={"dailyVo2Max": {}},
        payload_hash="test-hash",
    ))
    db.flush()

    body = client.get("/api/sync/status").json()
    vo2 = next(d for d in body["data_types"] if d["data_type"] == "daily-vo2-max")
    assert vo2["points_stored"] == 1


def test_sync_returns_409_when_not_connected(client):
    assert client.post("/api/sync").status_code == 409


def test_sync_returns_409_before_scheduling_any_background_work(client):
    """The connected check must happen before the background task is scheduled, not
    after -- confirmed here by no SyncRun row ever having been touched."""
    response = client.post("/api/sync")
    assert response.status_code == 409
    status = client.get("/api/sync/status").json()["sync"]
    assert status["running"] is False
    assert status["started_at"] is None


@respx.mock
def test_sync_returns_202_and_completes_in_the_background(client, db):
    """POST /api/sync must return promptly (202) rather than block for the whole sync
    -- the outcome (including `parse_errors`, added so a caller can tell a parse
    failure from a clean sync) is observed via GET /api/sync/status's `sync` field, not
    the POST response body, since the work now runs in a background task."""
    db.add(
        OAuthCredential(
            id=1,
            refresh_token="rt",
            access_token="still-valid",
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            scopes=[],
        )
    )
    db.flush()
    respx.get(url__startswith=f"{HEALTH_API_BASE_URL}/users/me/dataTypes/").mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )

    response = client.post("/api/sync")
    assert response.status_code == 202
    assert response.json() == {"status": "started"}

    # TestClient drives the ASGI app -- including its BackgroundTasks -- to completion
    # before handing the response back here, so the background job has already run.
    status = client.get("/api/sync/status").json()["sync"]
    assert status["running"] is False
    assert status["started_at"] is not None
    assert status["finished_at"] is not None
    assert status["last_error"] is None
    assert status["last_weeks_scored"] is not None
    reports = status["last_reports"]
    assert {r["data_type"] for r in reports} == {s.data_type_id for s in DATA_TYPES}
    for report in reports:
        assert report.keys() == {"data_type", "days_written", "error", "parse_errors"}
        assert report["parse_errors"] == 0
        assert report["error"] is None


@respx.mock
def test_background_sync_failure_clears_running_and_is_recorded(client, db, monkeypatch):
    """If the background job dies unexpectedly, `running` must still clear -- otherwise
    the frontend would poll "Syncing..." forever with no way to learn it failed."""
    import bioage.api.routes_sync as routes_sync

    db.add(
        OAuthCredential(
            id=1,
            refresh_token="rt",
            access_token="still-valid",
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            scopes=[],
        )
    )
    db.flush()
    respx.get(url__startswith=f"{HEALTH_API_BASE_URL}/users/me/dataTypes/").mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )

    def boom(session):
        raise RuntimeError("scoring exploded")

    monkeypatch.setattr(routes_sync, "rescore_all", boom)

    client.post("/api/sync")

    status = client.get("/api/sync/status").json()["sync"]
    assert status["running"] is False
    assert status["last_error"] == "scoring exploded"


def test_background_job_rolls_back_after_a_genuine_db_level_failure(engine, monkeypatch):
    """A plain RuntimeError (the previous test) leaves the session perfectly usable --
    it never touched the database. A *genuine* DB-level failure (a bad statement) is
    different: Postgres aborts the underlying transaction, and every further statement
    on that session without an explicit rollback() first raises PendingRollbackError on
    top of the original error. Without routes_sync.py's `session.rollback()` as the
    first statement of the except handler, the handler's own attempt to clear
    `running` would itself raise, leaving it wedged at True forever.

    Calls _run_sync_job directly (bypassing the HTTP layer and BackgroundTasks) so this
    exercises exactly the function and code path in question, with a real DBAPI-level
    error against the actual test database. Deliberately does NOT use the shared `db`
    fixture: that fixture wraps every test in a SAVEPOINT so app-level commits stay
    contained, but a genuine DBAPI-level abort followed by a real rollback/recommit
    cycle interacts badly with that SAVEPOINT bookkeeping (the outer transaction can
    become deassociated from the connection). A plain, unwrapped Session against the
    same engine sidesteps that entirely -- this test cleans up its own row instead.
    """
    import bioage.api.routes_sync as routes_sync

    class NoOpSyncService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def sync_all(self):
            return []

    def poison(session):
        # A real DBAPI-level failure, not a Python-level one: this aborts the
        # underlying Postgres transaction.
        session.execute(text("SELECT 1/0"))

    monkeypatch.setattr(routes_sync, "SyncService", NoOpSyncService)
    monkeypatch.setattr(routes_sync, "rescore_all", poison)

    settings = Settings(database_url="unused-in-this-test")
    session = Session(bind=engine)
    try:
        # With the rollback fix, this must complete without raising -- the whole point
        # is that the except handler can still successfully clear `running` after a
        # DB-level failure. Without the fix, this line itself raises
        # PendingRollbackError.
        routes_sync._run_sync_job(lambda: nullcontext(session), settings)

        run = session.get(SyncRun, 1)
        assert run is not None
        assert run.running is False
        assert run.last_error is not None
    finally:
        session.close()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sync_run WHERE id = 1"))


def test_sync_returns_409_when_a_sync_is_already_running(client, db):
    """Nothing previously stopped two POSTs (or a POST racing the scheduled job) from
    running two SyncService passes over the same tables concurrently -- the SyncRun
    row makes the guard cheap."""
    db.add(
        OAuthCredential(
            id=1,
            refresh_token="rt",
            access_token="still-valid",
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
            scopes=[],
        )
    )
    db.add(SyncRun(id=1, running=True, started_at=datetime.now(UTC)))
    db.flush()

    response = client.post("/api/sync")

    assert response.status_code == 409
    assert "already" in response.json()["detail"].lower()
    # Nothing was scheduled: the running run's state is untouched, not overwritten by
    # a second background job.
    status = client.get("/api/sync/status").json()["sync"]
    assert status["running"] is True
    assert status["last_reports"] is None


def test_reconcile_stale_sync_run_clears_a_running_flag_left_by_a_restart(db):
    from bioage.api.routes_sync import reconcile_stale_sync_run

    db.add(SyncRun(id=1, running=True, started_at=datetime.now(UTC)))
    db.flush()

    reconcile_stale_sync_run(db)

    run = db.get(SyncRun, 1)
    assert run is not None
    assert run.running is False
    assert run.finished_at is not None
    # Not a fabricated success: the outcome is genuinely unknown, only recorded as
    # reconciled.
    assert run.last_error is not None
    assert run.last_weeks_scored is None


def test_reconcile_stale_sync_run_is_a_no_op_when_nothing_is_running(db):
    from bioage.api.routes_sync import reconcile_stale_sync_run

    # No SyncRun row at all yet -- must not create one or raise.
    reconcile_stale_sync_run(db)
    assert db.get(SyncRun, 1) is None

    # A settled run must be left exactly as it was, not overwritten.
    db.add(SyncRun(id=1, running=False, last_weeks_scored=5, last_error=None))
    db.flush()
    reconcile_stale_sync_run(db)
    run = db.get(SyncRun, 1)
    assert run is not None
    assert run.running is False
    assert run.last_weeks_scored == 5
    assert run.last_error is None


def test_auth_start_returns_503_without_google_credentials(client):
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 503


def test_daily_metrics_endpoint_returns_rows(seeded_client):
    rows = seeded_client.get("/api/daily-metrics").json()
    assert len(rows) > 0
    assert "date" in rows[0]


# --- OAuth CSRF state validation -------------------------------------------------
#
# /start issues a state and stores it in the module-level oauth_state_store; /callback
# must require it back, reject anything it doesn't recognize (missing, unknown,
# expired), and consume it on success so a replayed callback fails even with a
# previously-valid state.


def test_auth_callback_requires_state(client):
    response = client.get("/api/auth/google/callback?code=some-code", follow_redirects=False)
    assert response.status_code == 400
    assert "state" in response.json()["detail"].lower()


def test_auth_callback_rejects_an_unknown_state(client):
    response = client.get(
        "/api/auth/google/callback?code=some-code&state=never-issued",
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_auth_callback_rejects_an_expired_state(client):
    state = oauth_state_store.issue()
    # Backdate the issuance past the TTL so the callback sees it as expired, without
    # sleeping the test. Reaching into the store's internal dict is test-only; the
    # store exposes no other way to age an entry.
    oauth_state_store._issued[state] = datetime.now(UTC) - timedelta(hours=1)

    response = client.get(
        f"/api/auth/google/callback?state={state}&code=some-code", follow_redirects=False
    )

    assert response.status_code == 400


def test_auth_callback_rejects_a_replayed_state(client):
    state = oauth_state_store.issue()

    first = client.get(f"/api/auth/google/callback?state={state}", follow_redirects=False)
    # No code was supplied, so the exchange itself never happens -- but the state must
    # already be consumed by this point.
    assert first.status_code == 400

    second = client.get(
        f"/api/auth/google/callback?state={state}&code=some-code", follow_redirects=False
    )
    assert second.status_code == 400


@respx.mock
def test_auth_callback_happy_path_exchanges_code_and_consumes_state(client, db):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "scope": "a b",
            },
        )
    )
    state = oauth_state_store.issue()

    response = client.get(
        f"/api/auth/google/callback?state={state}&code=good-code", follow_redirects=False
    )

    assert response.status_code == 307
    assert response.headers["location"].endswith("/connection?connected=1")
    credential = db.get(OAuthCredential, 1)
    assert credential is not None
    assert credential.refresh_token == "rt"

    # The state was single-use: replaying it must now fail.
    replay = client.get(
        f"/api/auth/google/callback?state={state}&code=good-code", follow_redirects=False
    )
    assert replay.status_code == 400
