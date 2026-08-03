"""Optional daily sync job.

Disabled by default: a freshly installed personal app should not make network calls the
user did not ask for.
"""

from __future__ import annotations

import logging

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from bioage.config import Settings
from bioage.db.base import session_factory
from bioage.ingest.client import GoogleHealthClient
from bioage.ingest.oauth import access_token
from bioage.ingest.sync import SyncService
from bioage.scoring import rescore_all

logger = logging.getLogger(__name__)


def run_scheduled_sync(settings: Settings) -> None:
    with session_factory(settings.database_url)() as session, httpx.Client(timeout=30) as http:
        client = GoogleHealthClient(
            token_provider=lambda: access_token(session, settings, http),
            force_refresh=lambda: access_token(session, settings, http, force=True),
        )
        reports = SyncService(session, client, settings.backfill_days).sync_all()
        rescore_all(session)
        session.commit()
    failed = [r.data_type for r in reports if r.error]
    logger.info("scheduled sync complete; %d data types failed: %s", len(failed), failed)


def start_scheduler(settings: Settings) -> BackgroundScheduler | None:
    if not settings.sync_schedule_enabled:
        return None
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_sync,
        trigger=CronTrigger.from_crontab(settings.sync_schedule_cron),
        args=[settings],
        id="daily-sync",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("sync scheduler started with cron %s", settings.sync_schedule_cron)
    return scheduler
