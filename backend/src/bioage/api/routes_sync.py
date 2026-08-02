"""Manual sync trigger and coverage reporting."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bioage.api.deps import get_app_settings, get_http_client, get_session
from bioage.api.schemas import CoverageOut, SyncStatusOut
from bioage.config import Settings
from bioage.db.models import OAuthCredential, RawDataPoint, SyncState
from bioage.ingest.client import GoogleHealthClient
from bioage.ingest.oauth import access_token
from bioage.ingest.registry import DATA_TYPES, DataTypeSpec
from bioage.ingest.sync import SyncService
from bioage.scoring import rescore_all

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
    )


@router.post("")
def trigger_sync(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    http: httpx.Client = Depends(get_http_client),
) -> dict[str, Any]:
    if session.get(OAuthCredential, 1) is None:
        raise HTTPException(status_code=409, detail="Not connected to Google Health")

    client = GoogleHealthClient(token_provider=lambda: access_token(session, settings, http))
    reports = SyncService(session, client, settings.backfill_days).sync_all()
    weeks = rescore_all(session)
    session.commit()
    return {
        "weeks_scored": weeks,
        "reports": [
            {
                "data_type": r.data_type,
                "days_written": r.days_written,
                "error": r.error,
                "parse_errors": r.parse_errors,
            }
            for r in reports
        ],
    }
