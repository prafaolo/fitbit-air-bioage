"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bioage.api import routes_auth, routes_bioage, routes_profile, routes_sync
from bioage.config import Settings, get_settings
from bioage.db.base import session_factory
from bioage.ingest.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _reconcile_stale_sync_state(settings: Settings) -> None:
    """Best-effort: a container that was killed mid-sync leaves `sync_run.running`
    stuck at True, which wedges Connection.tsx's "Sync now" button indefinitely
    (see routes_sync.reconcile_stale_sync_run). Failure to reconcile it must not
    prevent the app from starting -- the DB may not even be reachable yet -- so this
    logs and moves on rather than raising.
    """
    try:
        with session_factory(settings.database_url)() as session:
            routes_sync.reconcile_stale_sync_run(session)
    except Exception:
        logger.warning("could not reconcile stale sync_run state at startup", exc_info=True)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Fitbit Air Biological Age", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_bioage.router)
    app.include_router(routes_profile.router)
    app.include_router(routes_sync.router)
    app.include_router(routes_auth.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _reconcile_stale_sync_state(settings)
    start_scheduler(settings)
    return app
