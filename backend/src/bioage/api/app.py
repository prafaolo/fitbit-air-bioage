"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bioage.api import routes_auth, routes_bioage, routes_profile, routes_sync
from bioage.config import get_settings
from bioage.ingest.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)


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

    start_scheduler(settings)
    return app
