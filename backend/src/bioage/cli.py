"""Command-line entry points."""

from __future__ import annotations

import typer

from bioage.config import get_settings
from bioage.db.base import session_factory
from bioage.demo.generator import seed_demo
from bioage.scoring import rescore_all

app = typer.Typer(help="Fitbit Air biological age tooling.")


@app.command("seed-demo")
def seed_demo_command(days: int = 400) -> None:
    """Populate the database with synthetic history so the app runs without credentials."""
    with session_factory(get_settings().database_url)() as session:
        weeks = seed_demo(session, days=days)
        session.commit()
    typer.echo(f"Seeded {days} days of demo data and scored {weeks} weeks.")


@app.command("rescore")
def rescore_command() -> None:
    """Recompute every weekly score from the stored daily metrics."""
    with session_factory(get_settings().database_url)() as session:
        weeks = rescore_all(session)
        session.commit()
    typer.echo(f"Rescored {weeks} weeks.")


if __name__ == "__main__":
    app()
