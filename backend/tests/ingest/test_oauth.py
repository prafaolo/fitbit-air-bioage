from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from bioage.config import Settings
from bioage.db.models import OAuthCredential
from bioage.ingest.oauth import (
    NotConnectedError,
    access_token,
    build_authorization_url,
    exchange_code,
    store_credentials,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@db:5432/x",
        google_client_id="client-123",
        google_client_secret="secret-456",
        oauth_redirect_uri="http://localhost:8000/api/auth/google/callback",
    )


def test_authorization_url_requests_all_three_scopes(settings):
    query = parse_qs(urlparse(build_authorization_url(settings, state="abc")).query)
    assert len(query["scope"][0].split()) == 3
    assert "googlehealth.sleep.readonly" in query["scope"][0]


def test_authorization_url_forces_a_refresh_token(settings):
    """Without access_type=offline and prompt=consent, Google may omit the refresh token."""
    query = parse_qs(urlparse(build_authorization_url(settings, state="abc")).query)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["response_type"] == ["code"]


def test_authorization_url_carries_client_id_redirect_and_state(settings):
    query = parse_qs(urlparse(build_authorization_url(settings, state="xyz")).query)
    assert query["client_id"] == ["client-123"]
    assert query["state"] == ["xyz"]
    assert query["redirect_uri"] == ["http://localhost:8000/api/auth/google/callback"]


@respx.mock
def test_exchange_code_posts_the_authorization_code(settings):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3599}
    ))
    result = exchange_code(settings, code="the-code", http=httpx.Client())
    assert result["refresh_token"] == "rt"
    body = dict(parse_qs(route.calls[0].request.content.decode()))
    assert body["code"] == ["the-code"]
    assert body["grant_type"] == ["authorization_code"]


@respx.mock
def test_exchange_code_raises_on_failure(settings):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "bad_verifier"}))
    with pytest.raises(RuntimeError, match="bad_verifier"):
        exchange_code(settings, code="nope", http=httpx.Client())


def test_store_credentials_persists_a_singleton(db):
    for token in ("rt-1", "rt-2"):
        store_credentials(db, {
            "access_token": "at", "refresh_token": token, "expires_in": 3600,
            "scope": "a b",
        })
    db.flush()
    assert db.query(OAuthCredential).count() == 1
    assert db.get(OAuthCredential, 1).refresh_token == "rt-2"


def test_store_credentials_keeps_the_existing_refresh_token_when_google_omits_it(db):
    """Google returns refresh_token only on first consent; a refresh response lacks it."""
    store_credentials(db, {"access_token": "at1", "refresh_token": "rt", "expires_in": 3600})
    store_credentials(db, {"access_token": "at2", "expires_in": 3600})
    db.flush()
    assert db.get(OAuthCredential, 1).refresh_token == "rt"
    assert db.get(OAuthCredential, 1).access_token == "at2"


def test_store_credentials_raises_when_no_refresh_token_and_none_stored(db):
    """If Google omits the refresh token and none is on file, the user must reconnect --
    silently storing an empty refresh_token would break unattended sync later."""
    with pytest.raises(RuntimeError, match="Revoke.*reconnect"):
        store_credentials(db, {"access_token": "at", "expires_in": 3600})
    db.flush()
    assert db.query(OAuthCredential).count() == 0


def test_access_token_raises_when_not_connected(db, settings):
    with pytest.raises(NotConnectedError):
        access_token(db, settings, http=httpx.Client())


def test_access_token_returns_the_stored_token_while_valid(db, settings):
    future = datetime.now(UTC) + timedelta(hours=1)
    db.add(OAuthCredential(id=1, refresh_token="rt", access_token="still-good",
                           token_expiry=future, scopes=[]))
    db.flush()
    assert access_token(db, settings, http=httpx.Client()) == "still-good"


@respx.mock
def test_access_token_refreshes_when_expired(db, settings):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "fresh", "expires_in": 3599}
    ))
    past = datetime.now(UTC) - timedelta(minutes=5)
    db.add(OAuthCredential(id=1, refresh_token="rt", access_token="stale",
                           token_expiry=past, scopes=[]))
    db.flush()
    assert access_token(db, settings, http=httpx.Client()) == "fresh"


@respx.mock
def test_access_token_force_refreshes_even_when_the_cached_token_looks_valid(db, settings):
    """force=True is what the HTTP client uses after Google returns 401 despite our
    local bookkeeping saying the token should still be good -- it must not trust the
    cache in that case."""
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "forced-fresh", "expires_in": 3599}
    ))
    future = datetime.now(UTC) + timedelta(hours=1)
    db.add(OAuthCredential(id=1, refresh_token="rt", access_token="looks-still-good",
                           token_expiry=future, scopes=[]))
    db.flush()
    assert access_token(db, settings, http=httpx.Client(), force=True) == "forced-fresh"


@respx.mock
def test_refresh_uses_the_refresh_token_grant(db, settings):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "fresh", "expires_in": 3599}
    ))
    db.add(OAuthCredential(id=1, refresh_token="rt-value", access_token=None,
                           token_expiry=None, scopes=[]))
    db.flush()
    access_token(db, settings, http=httpx.Client())
    body = dict(parse_qs(route.calls[0].request.content.decode()))
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["rt-value"]
