"""Manual sync trigger and coverage reporting.

POST /api/sync used to run the full 11-data-type sync plus rescore_all inline, inside
the HTTP request. Worst case with the client's retry budget (backend/src/bioage/ingest/
client.py) is on the order of minutes -- far too long for a synchronous request behind
a "Syncing..." label. It now runs as a FastAPI BackgroundTasks job: the endpoint
validates and schedules the work, returns 202 immediately, and the frontend polls
GET /api/sync/status (whose `sync` field mirrors the SyncRun singleton row) until the
run settles.

The background task cannot reuse the request's own `Session` -- FastAPI tears down
`Depends(get_session)`'s generator (closing that session) as soon as the endpoint
function returns, before background tasks run. `get_sync_session_cm` exists so
production gets a genuinely new session/connection for the background task, while
tests can override it to reuse the same transactional `db` fixture session the test
itself uses (see tests/api/test_routes.py) -- otherwise a background task opening its
own connection would never see data the test only `flush()`ed, not committed, into an
outer transaction the test's connection alone is inside.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bioage.api.deps import get_app_settings, get_session
from bioage.api.schemas import CoverageOut, SyncRunOut, SyncStatusOut, SyncTriggerOut
from bioage.config import Settings
from bioage.db.base import session_factory
from bioage.db.models import OAuthCredential, RawDataPoint, SyncRun, SyncState
from bioage.ingest.client import GoogleHealthClient
from bioage.ingest.oauth import access_token
from bioage.ingest.registry import DATA_TYPES, DataTypeSpec
from bioage.ingest.sync import SyncService
from bioage.scoring import rescore_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _coverage(
    spec: DataTypeSpec, states: dict[str, SyncState], counts: dict[str, int]
) -> CoverageOut:
    """Coverage for one data type, defaulting every state-derived field when the type
    has never been synced (no SyncState row has been written for it yet)."""
    state = states.get(spec.data_type_id)
    return CoverageOut(
        data_type=spec.data_type_id,
        synced_through=state.synced_through if state else None,
        last_run_at=state.last_run_at.isoformat() if state and state.last_run_at else None,
        last_error=state.last_error if state else None,
        expected_empty=spec.expected_empty,
        points_stored=counts.get(spec.data_type_id, 0),
    )


def _sync_run_out(run: SyncRun | None) -> SyncRunOut:
    if run is None:
        return SyncRunOut(
            running=False,
            started_at=None,
            finished_at=None,
            last_weeks_scored=None,
            last_reports=None,
            last_error=None,
        )
    return SyncRunOut(
        running=run.running,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        last_weeks_scored=run.last_weeks_scored,
        last_reports=run.last_reports,
        last_error=run.last_error,
    )


@router.get("/status", response_model=SyncStatusOut)
def get_status(session: Session = Depends(get_session)) -> SyncStatusOut:
    states = {s.data_type: s for s in session.execute(select(SyncState)).scalars().all()}
    counts = dict(
        session.execute(
            select(RawDataPoint.data_type, func.count()).group_by(RawDataPoint.data_type)
        ).all()
    )
    return SyncStatusOut(
        connected=session.get(OAuthCredential, 1) is not None,
        data_types=[_coverage(spec, states, counts) for spec in DATA_TYPES],
        sync=_sync_run_out(session.get(SyncRun, 1)),
    )


def get_sync_session_cm(
    settings: Settings = Depends(get_app_settings),
) -> Callable[[], AbstractContextManager[Session]]:
    """A factory for a session usable from the background task, once the request's own
    session has already been closed. Production gets a brand-new session/connection
    each call; tests override this dependency to hand back the same `db` fixture
    session instead (see module docstring)."""

    def factory() -> AbstractContextManager[Session]:
        return session_factory(settings.database_url)()

    return factory


def _run_sync_job(
    session_cm: Callable[[], AbstractContextManager[Session]], settings: Settings
) -> None:
    """The actual sync-and-rescore work, run via BackgroundTasks after the response
    that scheduled it has already gone out."""
    with session_cm() as session:
        run = session.get(SyncRun, 1) or SyncRun(id=1)
        run.running = True
        run.started_at = datetime.now(UTC)
        run.finished_at = None
        run.last_error = None
        session.merge(run)
        session.commit()

        try:
            with httpx.Client(timeout=30.0) as http:
                client = GoogleHealthClient(
                    token_provider=lambda: access_token(session, settings, http),
                    force_refresh=lambda: access_token(session, settings, http, force=True),
                )
                reports = SyncService(session, client, settings.backfill_days).sync_all()
                weeks = rescore_all(session)

            run = session.get(SyncRun, 1) or SyncRun(id=1)
            run.running = False
            run.finished_at = datetime.now(UTC)
            run.last_weeks_scored = weeks
            run.last_reports = [
                {
                    "data_type": r.data_type,
                    "days_written": r.days_written,
                    "error": r.error,
                    "parse_errors": r.parse_errors,
                }
                for r in reports
            ]
            run.last_error = None
            session.merge(run)
            session.commit()
        except Exception as exc:
            # A failure here (e.g. a database error, or every data type's fetch
            # failing) must still clear `running` and record something -- otherwise
            # the frontend would poll "Syncing..." forever with no way to know the
            # background job died.
            logger.exception("background sync job failed")
            run = session.get(SyncRun, 1) or SyncRun(id=1)
            run.running = False
            run.finished_at = datetime.now(UTC)
            run.last_error = str(exc)[:500]
            session.merge(run)
            session.commit()


@router.post("", response_model=SyncTriggerOut, status_code=202)
def trigger_sync(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    session_cm: Callable[[], AbstractContextManager[Session]] = Depends(get_sync_session_cm),
) -> dict[str, Any]:
    if session.get(OAuthCredential, 1) is None:
        raise HTTPException(status_code=409, detail="Not connected to Google Health")
    background_tasks.add_task(_run_sync_job, session_cm, settings)
    return {"status": "started"}
