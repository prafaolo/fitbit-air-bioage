"""Weekly scoring orchestration.

For every ISO week covered by the data, build the trailing 30-day feature window,
resolve the profile as it stood that week, run every applicable estimator, and persist
the composite. Writes are upserts keyed on week_start, so rescoring is idempotent.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bioage.biomarkers.features import (
    DailyRecord,
    build_vector,
    compute_coverage,
    window_records,
)
from bioage.db.models import BioAgeScore, DailyMetric
from bioage.estimators.composite import estimate_all
from bioage.profile import age_on, resolve_profile


def iso_week_starts(first_day: date, last_day: date) -> list[date]:
    """Every Monday from the week containing first_day through the week of last_day."""
    cursor = first_day - timedelta(days=first_day.weekday())
    weeks: list[date] = []
    while cursor <= last_day:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return weeks


def load_daily_records(session: Session) -> list[DailyRecord]:
    rows = session.execute(select(DailyMetric).order_by(DailyMetric.date)).scalars().all()
    return [
        DailyRecord(
            day=row.date,
            resting_hr_bpm=row.resting_hr_bpm,
            hrv_rmssd_ms=row.hrv_rmssd_ms,
            steps=float(row.steps) if row.steps is not None else None,
            active_zone_minutes=(
                float(row.active_zone_minutes) if row.active_zone_minutes is not None else None
            ),
            sleep_efficiency_pct=row.sleep_efficiency_pct,
            sleep_midpoint_local_min=row.sleep_midpoint_local_min,
            respiratory_rate_brpm=row.respiratory_rate_brpm,
            is_demo=row.is_demo,
        )
        for row in rows
    ]


def score_week(
    session: Session,
    week_start: date,
    records: list[DailyRecord] | None = None,
) -> BioAgeScore | None:
    """Compute and persist one week's score, or return None if it cannot be scored."""
    if records is None:
        records = load_daily_records(session)

    week_end = week_start + timedelta(days=7)
    window = window_records(records, window_end=week_end)
    if not window:
        return None

    profile = resolve_profile(session, as_of=week_end)
    if profile is None:
        return None

    chronological_age = age_on(profile.birthdate, week_end)
    vector = build_vector(
        window,
        chronological_age=chronological_age,
        sex=profile.sex,
        height_m=profile.height_m,
        weight_kg=profile.weight_kg,
        waist_cm=profile.waist_cm,
    )
    if vector is None:
        return None

    coverage = compute_coverage(window)
    composite = estimate_all(vector, low_confidence=coverage.is_low_confidence)
    if composite is None:
        return None

    score = session.get(BioAgeScore, week_start) or BioAgeScore(week_start=week_start)
    score.chronological_age = chronological_age
    score.composite_age = composite.age_years
    score.ci_low = composite.ci_low
    score.ci_high = composite.ci_high
    score.components = [asdict(c) for c in composite.components]
    score.coverage = coverage.as_dict()
    score.is_low_confidence = composite.is_low_confidence
    # A week is demo-tainted if *any* day feeding its trailing window came from
    # seed_demo, not just all of them: a week straddling the demo/real boundary is
    # exactly the kind of row a real-sync eviction must not leave behind unmarked.
    score.is_demo = any(record.is_demo for record in window)
    session.merge(score)
    return score


def rescore_all(session: Session) -> int:
    """Recompute every scorable week. Returns the number of weeks written."""
    records = load_daily_records(session)
    if not records:
        return 0

    days = [r.day for r in records]
    written = 0
    for week_start in iso_week_starts(min(days), max(days)):
        if score_week(session, week_start, records=records) is not None:
            written += 1
    return written
