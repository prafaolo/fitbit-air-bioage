"""Command-line entry points."""

from __future__ import annotations

import typer

from bioage.config import get_settings
from bioage.db.base import session_factory
from bioage.db.models import BioAgeScore, DailyMetric
from bioage.demo.generator import seed_demo
from bioage.ingest.sync import normalize_all
from bioage.scoring import rescore_all

app = typer.Typer(help="Fitbit Air biological age tooling.")


@app.command("seed-demo")
def seed_demo_command(days: int = 400) -> None:
    """Populate the database with synthetic history so the app runs without credentials."""
    with session_factory(get_settings().database_url)() as session:
        weeks = seed_demo(session, days=days)
        session.commit()
    typer.echo(f"Seeded {days} days of demo data and scored {weeks} weeks.")


@app.command("rebuild")
def rebuild_command(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Discard all derived data and rebuild it from the stored raw API payloads.

    Deletes every `daily_metrics` and `bioage_scores` row, then re-parses
    `raw_data_points` and rescores. Raw payloads, OAuth credentials, your profile and
    your measurements are never touched, so this makes no network calls.

    Two situations need this:

    * You ran `seed-demo` and have since connected real data. Demo rows are written
      straight into `daily_metrics` and are indistinguishable from parsed real ones, so
      they linger and get scored alongside your history. This clears them.
    * A parser was fixed. Re-deriving from the raw archive is exactly why raw payloads
      are stored before parsing -- no re-fetch, and nothing that has aged out of the
      API's 90-day window is lost.
    """
    if not yes:
        typer.confirm(
            "Delete all daily metrics and weekly scores, then rebuild them from stored "
            "raw payloads?",
            abort=True,
        )

    with session_factory(get_settings().database_url)() as session:
        removed_scores = session.query(BioAgeScore).delete()
        removed_metrics = session.query(DailyMetric).delete()
        session.flush()
        normalized = normalize_all(session)
        weeks = rescore_all(session)
        session.commit()

    typer.echo(
        f"Discarded {removed_metrics} daily metric row(s) and {removed_scores} weekly "
        f"score(s)."
    )
    typer.echo(f"Rebuilt {normalized} daily metric row(s) from stored raw payloads.")
    typer.echo(f"Scored {weeks} week(s).")


@app.command("rescore")
def rescore_command() -> None:
    """Recompute every weekly score from the stored daily metrics."""
    with session_factory(get_settings().database_url)() as session:
        weeks = rescore_all(session)
        session.commit()
    typer.echo(f"Rescored {weeks} weeks.")


@app.command("sync")
def sync_command() -> None:
    """Pull new data from the Google Health API and rescore."""
    import httpx

    from bioage.ingest.client import GoogleHealthClient
    from bioage.ingest.oauth import access_token
    from bioage.ingest.sync import SyncService

    settings = get_settings()
    with session_factory(settings.database_url)() as session, httpx.Client(timeout=30) as http:
        client = GoogleHealthClient(
            token_provider=lambda: access_token(session, settings, http),
            force_refresh=lambda: access_token(session, settings, http, force=True),
        )
        reports = SyncService(session, client, settings.backfill_days).sync_all()
        weeks = rescore_all(session)
        session.commit()

    for report in reports:
        status = f"ERROR: {report.error}" if report.error else f"{report.days_written} days"
        typer.echo(f"  {report.data_type}: {status}")
    typer.echo(f"Rescored {weeks} weeks.")


if __name__ == "__main__":
    app()
