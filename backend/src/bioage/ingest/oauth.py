"""Google OAuth 2.0 authorization-code flow.

The web flow is used rather than google-auth's InstalledAppFlow.run_local_server, which
opens a browser and binds a port on the machine running the code — neither of which works
from inside a container.

Google returns a refresh token only on the first consent, and only when access_type is
offline with prompt=consent. Refresh responses omit it, so stored refresh tokens are
never overwritten with None.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from bioage.config import Settings
from bioage.db.models import OAuthCredential
from bioage.ingest.registry import SCOPES

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Refresh slightly early so a token cannot expire mid-sync.
EXPIRY_MARGIN = timedelta(seconds=120)


class NotConnectedError(RuntimeError):
    """No Google credentials are stored; the user has not completed the OAuth flow."""


def build_authorization_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _post_token(http: httpx.Client, data: dict[str, str]) -> dict[str, Any]:
    response = http.post(TOKEN_URL, data=data)
    if response.status_code != 200:
        # Google's error body carries an error code/description, never the client secret
        # or a token value, so it is safe to surface verbatim.
        raise RuntimeError(
            f"Google token endpoint returned {response.status_code}: {response.text}"
        )
    result: dict[str, Any] = response.json()
    return result


def exchange_code(settings: Settings, code: str, http: httpx.Client) -> dict[str, Any]:
    return _post_token(
        http,
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.oauth_redirect_uri,
            "grant_type": "authorization_code",
        },
    )


def store_credentials(session: Session, token_response: dict[str, Any]) -> OAuthCredential:
    credential = session.get(OAuthCredential, 1) or OAuthCredential(id=1, refresh_token="")

    refresh_token = token_response.get("refresh_token")
    if refresh_token:
        credential.refresh_token = refresh_token
    elif not credential.refresh_token:
        raise RuntimeError(
            "Google did not return a refresh token. Revoke the app's access in your Google "
            "Account and reconnect so consent is prompted again."
        )

    credential.access_token = token_response.get("access_token")
    expires_in = token_response.get("expires_in")
    credential.token_expiry = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
    )
    scope = token_response.get("scope")
    if scope:
        credential.scopes = scope.split()
    return session.merge(credential)


def access_token(
    session: Session,
    settings: Settings,
    http: httpx.Client,
    now: datetime | None = None,
) -> str:
    """Return a currently valid access token, refreshing it if necessary."""
    credential = session.get(OAuthCredential, 1)
    if credential is None:
        raise NotConnectedError("No Google credentials stored. Complete the OAuth flow first.")

    moment = now or datetime.now(UTC)
    if (
        credential.access_token
        and credential.token_expiry
        and credential.token_expiry - EXPIRY_MARGIN > moment
    ):
        return credential.access_token

    refreshed = _post_token(
        http,
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": credential.refresh_token,
            "grant_type": "refresh_token",
        },
    )
    stored = store_credentials(session, refreshed)
    session.flush()
    if not stored.access_token:
        raise RuntimeError("Token refresh succeeded but returned no access token")
    return stored.access_token
