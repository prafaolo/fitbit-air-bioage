"""Biological age series and per-week detail."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bioage.api.deps import get_session
from bioage.api.schemas import DailyMetricOut, SeriesPoint, WeekDetail
from bioage.db.models import BioAgeScore, DailyMetric

router = APIRouter(prefix="/api", tags=["bioage"])


@router.get("/bioage/series", response_model=list[SeriesPoint])
def get_series(
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session = Depends(get_session),
) -> list[BioAgeScore]:
    stmt = select(BioAgeScore).order_by(BioAgeScore.week_start)
    if from_date:
        stmt = stmt.where(BioAgeScore.week_start >= from_date)
    if to_date:
        stmt = stmt.where(BioAgeScore.week_start <= to_date)
    return list(session.execute(stmt).scalars().all())


@router.get("/bioage/weeks/{week_start}", response_model=WeekDetail)
def get_week(week_start: date, session: Session = Depends(get_session)) -> BioAgeScore:
    score = session.get(BioAgeScore, week_start)
    if score is None:
        raise HTTPException(status_code=404, detail=f"No score for week starting {week_start}")
    return score


@router.get("/daily-metrics", response_model=list[DailyMetricOut])
def get_daily_metrics(
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session = Depends(get_session),
) -> list[DailyMetric]:
    stmt = select(DailyMetric).order_by(DailyMetric.date)
    if from_date:
        stmt = stmt.where(DailyMetric.date >= from_date)
    if to_date:
        stmt = stmt.where(DailyMetric.date <= to_date)
    return list(session.execute(stmt).scalars().all())
