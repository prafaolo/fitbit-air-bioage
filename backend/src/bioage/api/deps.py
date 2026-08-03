"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
from sqlalchemy.orm import Session

from bioage.config import Settings, get_settings
from bioage.db.base import session_factory


def get_session() -> Iterator[Session]:
    with session_factory(get_settings().database_url)() as session:
        yield session


def get_app_settings() -> Settings:
    return get_settings()


def get_http_client() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=30.0) as client:
        yield client
