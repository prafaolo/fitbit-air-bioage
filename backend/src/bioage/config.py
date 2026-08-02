"""Application settings, sourced from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # Scheduling is opt-in so a fresh install never makes unexpected network calls.
    sync_schedule_enabled: bool = False
    sync_schedule_cron: str = "0 5 * * *"

    # How far back the first sync attempts to backfill, subject to per-data-type caps.
    backfill_days: int = 90

    frontend_origin: str = "http://localhost:5173"

    @property
    def is_google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
