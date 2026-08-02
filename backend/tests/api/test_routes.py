from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from bioage.api.app import create_app
from bioage.api.deps import get_session
from bioage.api.routes_auth import oauth_state_store
from bioage.db.models import OAuthCredential
from bioage.demo.generator import seed_demo
from bioage.ingest.client import BASE_URL as HEALTH_API_BASE_URL
from bioage.ingest.registry import DATA_TYPES

TOKEN_URL = "https://oauth2.googleapis.com/token"


@pytest.fixture
def client(db):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
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


def test_sync_status_lists_vo2max_as_expected_empty(client):
    body = client.get("/api/sync/status").json()
    vo2 = next(d for d in body["data_types"] if d["data_type"] == "daily-vo2-max")
    assert vo2["expected_empty"] is True


def test_sync_returns_409_when_not_connected(client):
    assert client.post("/api/sync").status_code == 409


@respx.mock
def test_sync_succeeds_when_connected_and_reports_parse_errors_per_type(client, db):
    """The only prior sync test covered the 409 path; this covers the success response
    shape, in particular `parse_errors` -- the field this task was specifically asked
    to add to the response -- so renaming or dropping it would fail a test."""
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

    assert response.status_code == 200
    body = response.json()
    assert "weeks_scored" in body
    assert {r["data_type"] for r in body["reports"]} == {s.data_type_id for s in DATA_TYPES}
    for report in body["reports"]:
        assert report.keys() == {"data_type", "days_written", "error", "parse_errors"}
        assert report["parse_errors"] == 0
        assert report["error"] is None


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
