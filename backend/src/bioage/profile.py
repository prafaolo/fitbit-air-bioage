"""Resolve the subject's profile as it stood on a given date.

Weekly scores are computed for past weeks, so the profile must be resolved *as of* that
week rather than from today's values. Otherwise re-measuring your waist in July would
silently rewrite every score back to May.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from bioage.db.models import DailyMetric, Measurement, Profile
from bioage.types import Sex

DAYS_PER_YEAR = 365.2425


@dataclass(frozen=True)
class ResolvedProfile:
    sex: Sex
    birthdate: date
    height_m: float | None
    weight_kg: float | None
    waist_cm: float | None


def age_on(birthdate: date, day: date) -> float:
    """Chronological age in years, including the fractional part."""
    return (day - birthdate).days / DAYS_PER_YEAR


def _latest_measurement(session: Session, kind: str, as_of: date) -> float | None:
    stmt = (
        select(Measurement.value)
        .where(Measurement.kind == kind, Measurement.measured_on <= as_of)
        .order_by(Measurement.measured_on.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _latest_api_value(
    session: Session, column: InstrumentedAttribute[float | None], as_of: date
) -> float | None:
    stmt = (
        select(column)
        .where(column.isnot(None), DailyMetric.date <= as_of)
        .order_by(DailyMetric.date.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def resolve_profile(session: Session, as_of: date) -> ResolvedProfile | None:
    profile = session.get(Profile, 1)
    if profile is None:
        return None

    # Manual measurements always win; API values only fill gaps.
    height = _latest_measurement(session, "height_m", as_of)
    if height is None:
        height = _latest_api_value(session, DailyMetric.height_m, as_of)

    weight = _latest_measurement(session, "weight_kg", as_of)
    if weight is None:
        weight = _latest_api_value(session, DailyMetric.weight_kg, as_of)

    return ResolvedProfile(
        sex=profile.sex,
        birthdate=profile.birthdate,
        height_m=height,
        weight_kg=weight,
        waist_cm=_latest_measurement(session, "waist_cm", as_of),
    )
