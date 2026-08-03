"""Sync orchestration: fetch, store raw, normalize, advance the watermark.

Raw payloads are written before parsing so a parser fix never requires re-fetching data
that may have aged out of the API's queryable window. Each data type advances its own
watermark independently, and a failure in one does not abort the others: a wearable that
never populated VO2max should not block resting heart rate from syncing.

Failure isolation is enforced at two levels: a fetch failure aborts only that data
type's window (the watermark does not advance, so the next sync retries it), and within
a window a single malformed payload aborts only that payload's parse (recorded via
`SyncReport.parse_errors`) -- it does not stop the rest of the window from being parsed
and written, and it does not prevent the watermark from advancing. The watermark still
advances after parse errors because the raw payload was already durably stored: per this
module's central design decision, a parser fix is applied by re-parsing stored raw data
(`normalize_all`), never by re-fetching a window whose data may since have aged out of
the API's queryable range.

Every fetched payload is archived, including ones a parser cannot make sense of.
`RawDataPoint` is keyed on (data_type, point_date, payload_hash): when a payload fails
to parse, `point_date` falls back to the window's start date, so many distinct
unparseable payloads in one window would otherwise collide on the same (data_type,
point_date) pair and overwrite one another, leaving one arbitrary row behind out of what
might have been 90 archived days. The payload hash discriminates them without
sacrificing idempotency: re-fetching and re-syncing the same window reproduces the same
hashes, so `on_conflict_do_update` still updates existing rows in place rather than
duplicating them.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bioage.db.models import (
    BioAgeScore,
    DailyMetric,
    Measurement,
    Profile,
    RawDataPoint,
    SyncState,
)
from bioage.ingest.registry import DATA_TYPES, DataTypeSpec, get_spec
from bioage.types import DateRange

logger = logging.getLogger(__name__)

# Every table `seed_demo` writes to. `raw_data_points` is deliberately absent: seed_demo
# never writes there, so it holds no demo rows to evict.
_DEMO_TAGGED_MODELS = (DailyMetric, BioAgeScore, Measurement, Profile)


def evict_demo_data(session: Session) -> int:
    """Delete every `is_demo=True` row across all four provenance-tracked tables.

    Called once at the start of a sync run (see `SyncService.sync_all`), before any
    real payload is written, so demo history never sits alongside real data even for a
    single request. Deleting the demo `Profile` row is intentional, not collateral: the
    Profile page already treats a missing profile as a normal first-run state, which is
    a far better failure mode than silently scoring every week against a fake
    birthdate. Returns the number of rows deleted; 0 (the common case once a database
    has been synced once for real) means nothing was evicted and nothing is logged.
    """
    # Deliberately not synchronize_session=False: a Profile row deleted this way must
    # actually vanish from the session's identity map too, or a later session.get(
    # Profile, 1) in the same session/request (as resolve_profile does) would return a
    # stale, already-deleted instance instead of None -- silently resurrecting exactly
    # the bug this function exists to close. The default ("auto"/"evaluate") strategy
    # handles a plain `is_demo == True` filter without a fallback SELECT.
    total = 0
    for model in _DEMO_TAGGED_MODELS:
        total += session.query(model).filter_by(is_demo=True).delete()
    if total:
        logger.info(
            "cleared %d demo row(s) across daily_metrics/bioage_scores/measurements/"
            "profile because real data arrived",
            total,
        )
    return total


def _payload_hash(payload: dict[str, Any]) -> str:
    """A stable hash of a payload's canonical JSON form.

    `sort_keys=True` makes the hash independent of key order, which the API gives no
    guarantee about across requests for what is otherwise the same payload. This is the
    discriminator in `RawDataPoint`'s unique constraint -- see the module docstring.
    """
    canonical = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class DataPointSource(Protocol):
    def list_data_points(self, spec: DataTypeSpec, window: DateRange) -> list[dict]: ...


@dataclass(frozen=True)
class SyncReport:
    data_type: str
    points_fetched: int
    days_written: int
    error: str | None = None
    parse_errors: int = 0


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
        parse_errors = 0
        for payload in points:
            try:
                parsed = spec.parser(payload)
            except Exception as exc:
                # The parsers are total against *missing* fields but not against
                # *malformed* ones (an invalid proto Date, a non-numeric int64, ...);
                # one bad payload must not abandon the rest of an otherwise-good
                # window. Fall back to the same "unparseable" handling as a parser
                # that returns None, and count it so the caller can surface it.
                logger.warning(
                    "parse failed for %s payload: %s", spec.data_type_id, exc
                )
                parse_errors += 1
                parsed = None
            point_date = parsed.day if parsed else window.start
            self._session.execute(
                insert(RawDataPoint)
                .values(
                    data_type=spec.data_type_id,
                    point_date=point_date,
                    payload=payload,
                    payload_hash=_payload_hash(payload),
                )
                .on_conflict_do_update(
                    index_elements=[
                        RawDataPoint.data_type,
                        RawDataPoint.point_date,
                        RawDataPoint.payload_hash,
                    ],
                    set_={"payload": payload},
                )
            )
            if parsed:
                _upsert_daily(self._session, parsed.day, parsed.values)
                days_written += 1

        # The watermark advances even when some payloads failed to parse: every payload
        # in this window, parseable or not, was already durably written to
        # raw_data_points above, so nothing is lost by moving on. Re-fetching the same
        # window on the next sync would not fix a malformed payload -- only a parser fix
        # followed by normalize_all can -- and it would re-request data that may partly
        # age out of the API's queryable window before that fix ships.
        state.synced_through = today
        state.last_error = None
        self._session.merge(state)
        return SyncReport(spec.data_type_id, len(points), days_written, None, parse_errors)

    def sync_all(self, today: date | None = None) -> list[SyncReport]:
        moment = today or date.today()
        # Once per sync run, before any data type's first write, not once per data
        # type: a demo history must not survive even the very first real sync, and
        # nothing later in this loop should have to know or care that eviction happened.
        evict_demo_data(self._session)
        reports = []
        for spec in DATA_TYPES:
            try:
                reports.append(self.sync_data_type(spec, moment))
            except Exception as exc:
                # Defense in depth: sync_data_type already contains the failures it
                # knows how to name (fetch errors, per-payload parse errors). Anything
                # that still escapes it (e.g. a database error) must not discard the
                # reports already collected for the data types processed before it.
                logger.warning(
                    "sync_data_type raised unexpectedly for %s: %s", spec.data_type_id, exc
                )
                reports.append(SyncReport(spec.data_type_id, 0, 0, error=str(exc)))
        return reports


def normalize_all(session: Session) -> int:
    """Re-parse every stored raw payload into daily_metrics. No network access."""
    rows = session.execute(select(RawDataPoint)).scalars().all()
    written = 0
    for row in rows:
        try:
            spec = get_spec(row.data_type)
        except KeyError:
            continue
        try:
            parsed = spec.parser(row.payload)
        except Exception as exc:
            # Same rationale as the per-payload guard in sync_data_type: one malformed
            # stored payload must not abort re-parsing of every other row.
            logger.warning("re-parse failed for %s row: %s", row.data_type, exc)
            continue
        if parsed:
            _upsert_daily(session, parsed.day, parsed.values)
            written += 1
    return written
