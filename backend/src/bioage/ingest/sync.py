"""Sync orchestration: fetch, store raw, normalize, advance the watermark.

Raw payloads are written before parsing so a parser fix never requires re-fetching data
that may have aged out of the API's queryable window. Each data type advances its own
watermark independently, and a failure in one does not abort the others: a wearable that
never populated VO2max should not block resting heart rate from syncing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bioage.db.models import DailyMetric, RawDataPoint, SyncState
from bioage.ingest.registry import DATA_TYPES, DataTypeSpec, get_spec
from bioage.types import DateRange

logger = logging.getLogger(__name__)


class DataPointSource(Protocol):
    def list_data_points(self, spec: DataTypeSpec, window: DateRange) -> list[dict]: ...


@dataclass(frozen=True)
class SyncReport:
    data_type: str
    points_fetched: int
    days_written: int
    error: str | None = None


def _upsert_daily(session: Session, day: date, values: dict[str, float]) -> None:
    """Merge parsed values into the day's row without clobbering other data types."""
    if not values:
        return
    statement = (
        insert(DailyMetric)
        .values(date=day, **values)
        .on_conflict_do_update(index_elements=[DailyMetric.date], set_=values)
    )
    session.execute(statement)


class SyncService:
    def __init__(self, session: Session, client: DataPointSource, backfill_days: int) -> None:
        self._session = session
        self._client = client
        self._backfill_days = backfill_days

    def _window(self, spec: DataTypeSpec, today: date) -> DateRange | None:
        state = self._session.get(SyncState, spec.data_type_id)
        start = (
            state.synced_through
            if state and state.synced_through
            else today - timedelta(days=self._backfill_days)
        )
        return DateRange(start, today) if start < today else None

    def sync_data_type(self, spec: DataTypeSpec, today: date) -> SyncReport:
        window = self._window(spec, today)
        if window is None:
            return SyncReport(spec.data_type_id, 0, 0, None)

        state = self._session.get(SyncState, spec.data_type_id) or SyncState(
            data_type=spec.data_type_id
        )
        state.last_run_at = datetime.now(UTC)

        try:
            points = self._client.list_data_points(spec, window)
        except Exception as exc:
            # A failure here must be reported, not raised: one data type's outage (a
            # wearable that never populated VO2max, a transient 5xx on one endpoint)
            # must not stop the others in sync_all from running.
            logger.warning("sync failed for %s: %s", spec.data_type_id, exc)
            state.last_error = str(exc)[:500]
            self._session.merge(state)
            return SyncReport(spec.data_type_id, 0, 0, error=str(exc))

        days_written = 0
        for payload in points:
            parsed = spec.parser(payload)
            if parsed is None and spec.expected_empty:
                # This data type is not expected to be populated for this device (e.g.
                # VO2max, whose parser is a deliberate no-op). Without this guard, every
                # unparseable payload in the window would collide on the same raw-row
                # key (data_type, window.start) and silently overwrite one another,
                # leaving at most one arbitrary row behind. Since the parser can never
                # extract anything from these payloads anyway, skipping the raw write
                # loses nothing and avoids a misleading partial archive.
                continue
            point_date = parsed.day if parsed else window.start
            self._session.execute(
                insert(RawDataPoint)
                .values(data_type=spec.data_type_id, point_date=point_date, payload=payload)
                .on_conflict_do_update(
                    index_elements=[RawDataPoint.data_type, RawDataPoint.point_date],
                    set_={"payload": payload},
                )
            )
            if parsed:
                _upsert_daily(self._session, parsed.day, parsed.values)
                days_written += 1

        state.synced_through = today
        state.last_error = None
        self._session.merge(state)
        return SyncReport(spec.data_type_id, len(points), days_written, None)

    def sync_all(self, today: date | None = None) -> list[SyncReport]:
        moment = today or date.today()
        return [self.sync_data_type(spec, moment) for spec in DATA_TYPES]


def normalize_all(session: Session) -> int:
    """Re-parse every stored raw payload into daily_metrics. No network access."""
    rows = session.execute(select(RawDataPoint)).scalars().all()
    written = 0
    for row in rows:
        try:
            spec = get_spec(row.data_type)
        except KeyError:
            continue
        parsed = spec.parser(row.payload)
        if parsed:
            _upsert_daily(session, parsed.day, parsed.values)
            written += 1
    return written
