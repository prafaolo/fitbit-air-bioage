"""Command-line entry points."""

from __future__ import annotations

import typer

from bioage.config import get_settings
from bioage.db.base import session_factory
from bioage.db.models import BioAgeScore, DailyMetric
from bioage.demo.generator import RealDataExistsError, seed_demo
from bioage.ingest.sync import normalize_all
from bioage.scoring import rescore_all

app = typer.Typer(help="Fitbit Air biological age tooling.")


@app.command("seed-demo")
def seed_demo_command(
    days: int = 400,
    force: bool = typer.Option(
        False,
        "--force",
        help="Seed demo data even though this database already holds real synced data.",
    ),
) -> None:
    """Populate the database with synthetic history so the app runs without credentials.

    Refuses if the database already holds real synced data (any `raw_data_points` rows,
    or `daily_metrics` rows not already marked demo) -- seeding synthetic history on top
    of a real one would recreate the exact provenance bug `is_demo` exists to prevent,
    just in the opposite direction. Pass `--force` to seed anyway.
    """
    with session_factory(get_settings().database_url)() as session:
        try:
            weeks = seed_demo(session, days=days, force=force)
        except RealDataExistsError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        session.commit()
    typer.echo(f"Seeded {days} days of demo data and scored {weeks} weeks.")


@app.command("rebuild")
def rebuild_command(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Discard all derived data and rebuild it from the stored raw API payloads.

    Deletes every `daily_metrics` and `bioage_scores` row, then re-parses
    `raw_data_points` and rescores. Raw payloads, OAuth credentials, your profile and
    your measurements are never touched, so this makes no network calls. Every row this
    rebuilds comes from `raw_data_points`, which `seed-demo` never writes to, so the
    result is always real data (`is_demo=False`).

    Demo data left over from `seed-demo` no longer needs this: your first real sync now
    clears it automatically, the moment real data arrives, tagged rows and all. What
    this command remains the right tool for is re-deriving `daily_metrics` after a
    parser fix -- exactly why raw payloads are stored before parsing in the first place,
    no re-fetch, and nothing that has aged out of the API's 90-day window is lost.
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
