"""Google OAuth endpoints.

`state` is standard OAuth CSRF protection: without validating it, anyone who can get the
operator's browser to open /callback with a `code` and `state` of their own choosing
could bind this app to an attacker-controlled Google account. Task 21 issues the OAuth
module itself (`bioage.ingest.oauth`) without any state handling and deliberately left
validation to this task; `/start` generates and stores the state it issues, `/callback`
requires it back and consumes it on first use.

`_OAuthStateStore` is a plain in-process dict, not a database table or a dependency on a
cache service: state tokens live for minutes, only matter within a single OAuth round
trip, and this app is single-user and single-process, so there is nothing to share across
requests other than process memory. A restart mid-flow simply forces the user to click
"Connect" again.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from bioage.api.deps import get_app_settings, get_http_client, get_session
from bioage.config import Settings
from bioage.db.models import OAuthCredential
from bioage.ingest.oauth import build_authorization_url, exchange_code, store_credentials

router = APIRouter(prefix="/api/auth/google", tags=["auth"])

# A Google consent screen round trip (including any account picker or 2FA prompt) should
# comfortably finish within a couple of minutes; ten minutes gives headroom without
# leaving stale states valid for long.
STATE_TTL = timedelta(minutes=10)


class OAuthStateStore:
    """Single-use, TTL-bounded store for OAuth CSRF state tokens."""

    def __init__(self, ttl: timedelta = STATE_TTL) -> None:
        self._ttl = ttl
        self._issued: dict[str, datetime] = {}

    def issue(self) -> str:
        token = secrets.token_urlsafe(16)
        self._issued[token] = datetime.now(UTC)
        return token

    def consume(self, token: str, now: datetime | None = None) -> bool:
        """True iff `token` was issued and is still within its TTL.

        Pops the token unconditionally (whether or not it turns out to be expired), so a
        state can only ever be accepted once -- a replayed value, valid or not, always
        fails.
        """
        issued_at = self._issued.pop(token, None)
        if issued_at is None:
            return False
        moment = now or datetime.now(UTC)
        return moment - issued_at <= self._ttl


# Module-level singleton: the app is single-process, and routes need a shared store
# across the /start and /callback requests of one OAuth round trip.
oauth_state_store = OAuthStateStore()


@router.get("/start")
def start(settings: Settings = Depends(get_app_settings)) -> RedirectResponse:
    if not settings.is_google_configured:
        raise HTTPException(
            status_code=503,
            detail="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set. See docs/SETUP.md.",
        )
    state = oauth_state_store.issue()
    return RedirectResponse(build_authorization_url(settings, state=state))


@router.get("/callback")
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    http: httpx.Client = Depends(get_http_client),
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"Google returned an error: {error}")
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")
    if not oauth_state_store.consume(state):
        raise HTTPException(
            status_code=400, detail="State parameter is unknown, expired, or already used"
        )
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        store_credentials(session, exchange_code(settings, code, http))
    except RuntimeError as exc:
        # Both exchange_code and store_credentials raise RuntimeError with messages
        # that are safe and actionable to show the user (Google's error body, or
        # guidance to revoke-and-reconnect when no refresh token is available) --
        # surface them instead of letting this become a bare 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return RedirectResponse(f"{settings.frontend_origin}/connection?connected=1")


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict[str, Any]:
    credential = session.get(OAuthCredential, 1)
    return {
        "connected": credential is not None,
        "connected_at": credential.connected_at.isoformat() if credential else None,
        "scopes": credential.scopes if credential else [],
    }
