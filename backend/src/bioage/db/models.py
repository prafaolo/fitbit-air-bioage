"""ORM models.

Raw payloads are stored before parsing so that a parser fix is a re-parse rather than a
re-fetch of data that may have aged out of the API's queryable window.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bioage.db.base import Base
from bioage.types import Sex

MEASUREMENT_KINDS = ("height_m", "weight_kg", "waist_cm")


class RawDataPoint(Base):
    """One archived payload as fetched from the Google Health API.

    Keyed on (data_type, point_date, payload_hash), not just (data_type, point_date).
    A parser that returns None for a payload falls back to keying it on the window
    start date (see bioage.ingest.sync), which means many distinct unparseable
    payloads in the same window would otherwise share a key. The hash discriminates
    them so a parser regression can never silently collapse 90 archived days down to
    one arbitrary row -- while still keeping re-syncs of an identical payload
    idempotent (same hash -> same conflict target -> update in place, not a new row).
    """

    __tablename__ = "raw_data_points"
    __table_args__ = (
        UniqueConstraint(
            "data_type", "point_date", "payload_hash", name="uq_raw_type_date_hash"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    point_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DailyMetric(Base):
    """One normalized row per calendar day. Every measurement is optional."""

    __tablename__ = "daily_metrics"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    resting_hr_bpm: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd_ms: Mapped[float | None] = mapped_column(Float)
    hrv_average_ms: Mapped[float | None] = mapped_column(Float)
    steps: Mapped[int | None] = mapped_column(Integer)
    active_zone_minutes: Mapped[int | None] = mapped_column(Integer)
    sleep_total_min: Mapped[float | None] = mapped_column(Float)
    sleep_efficiency_pct: Mapped[float | None] = mapped_column(Float)
    waso_min: Mapped[float | None] = mapped_column(Float)
    deep_pct: Mapped[float | None] = mapped_column(Float)
    rem_pct: Mapped[float | None] = mapped_column(Float)
    sleep_midpoint_local_min: Mapped[float | None] = mapped_column(Float)
    respiratory_rate_brpm: Mapped[float | None] = mapped_column(Float)
    spo2_pct: Mapped[float | None] = mapped_column(Float)
    skin_temp_delta_c: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    height_m: Mapped[float | None] = mapped_column(Float)


class Profile(Base):
    """Singleton row: this is a single-user application."""

    __tablename__ = "profile"
    __table_args__ = (CheckConstraint("id = 1", name="ck_profile_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    sex: Mapped[Sex] = mapped_column(
        Enum(Sex, name="sex", values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    birthdate: Mapped[date] = mapped_column(Date, nullable=False)


class Measurement(Base):
    """A dated body measurement.

    Dating matters: re-measuring your waist must not retroactively rewrite earlier
    weekly scores.
    """

    __tablename__ = "measurements"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('height_m', 'weight_kg', 'waist_cm')", name="ck_measurement_kind"
        ),
        UniqueConstraint("kind", "measured_on", name="uq_measurement_kind_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    measured_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)


class BioAgeScore(Base):
    __tablename__ = "bioage_scores"

    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    chronological_age: Mapped[float] = mapped_column(Float, nullable=False)
    composite_age: Mapped[float] = mapped_column(Float, nullable=False)
    ci_low: Mapped[float] = mapped_column(Float, nullable=False)
    ci_high: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[list] = mapped_column(JSONB, nullable=False)
    coverage: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    __table_args__ = (CheckConstraint("id = 1", name="ck_oauth_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SyncState(Base):
    """Per-data-type watermark, so incremental syncs fetch only what is new."""

    __tablename__ = "sync_state"

    data_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    synced_through: Mapped[date | None] = mapped_column(Date)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
