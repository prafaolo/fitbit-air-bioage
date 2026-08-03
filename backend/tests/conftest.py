"""Shared fixtures.

Integration tests need a real Postgres because the schema uses JSONB. Point
TEST_DATABASE_URL at a scratch database; `docker compose up -d db` provides one.

The `db` fixture joins the Session into an externally-managed transaction using the
SAVEPOINT recipe from SQLAlchemy's testing docs ("Joining a Session into an External
Transaction"). A naive version of this fixture binds the Session directly to a
Connection that already has an open transaction and rolls that transaction back at
teardown. That works as long as tests only ever `flush()`. But later tasks (the
FastAPI routes, the scoring pipeline) call `session.commit()` inside the code under
test, and a plain `session.commit()` would commit the *outer* transaction too -
leaking committed rows into the next test. To contain that, we open a SAVEPOINT
(`begin_nested`) before yielding the session, and an `after_transaction_end` listener
re-opens a fresh SAVEPOINT every time the previous one ends (including when
application code calls `session.commit()`, which ends the SAVEPOINT but not the outer
transaction). The outer transaction is rolled back at teardown, discarding everything
regardless of how many inner commits happened.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from bioage.db.base import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://bioage:bioage@localhost:5432/bioage_test"
)


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `bioage.config.get_settings()` constructible with no `.env` file present.

    `create_app()` (task 23) is the first code path exercised by the test suite that
    calls `get_settings()` outside of `cli.py`, and `Settings.database_url` has no
    default -- without this, `uv run pytest` fails before a single test runs on a
    fresh clone. `DATABASE_URL` is set to the same value the `engine` fixture uses, so
    a test that accidentally bypassed the `get_session` override would hit the same
    scratch database rather than a stray production one. Google credentials are left
    unset so the `/api/auth/google/start` 503-without-credentials test still passes.
    """
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:5173")


@pytest.fixture(scope="session")
def engine():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()

    eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    """A session whose entire effect - including any inner `commit()` calls made by
    application code under test - is rolled back after the test.
    """
    connection = engine.connect()
    outer_transaction = connection.begin()

    session = Session(bind=connection)
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(session: Session, transaction: object) -> None:
        # Checking the *connection's* own nested-transaction state (`nested.is_active`)
        # rather than inspecting the ORM SessionTransaction object hierarchy (the
        # previous version of this recipe checked `transaction.nested and not
        # transaction._parent.nested`) is what makes this robust to application code
        # calling `session.rollback()`, not just `session.commit()`. Both end the
        # active SAVEPOINT, but SQLAlchemy's rollback() propagates differently through
        # the ORM's own transaction-object hierarchy than commit() does; inferring the
        # restart condition from that hierarchy worked for commit-only code paths but
        # under a real rollback could leave the SAVEPOINT never reopened, letting a
        # later commit from application code reach -- and "deassociate" -- the outer,
        # externally-managed transaction this fixture rolls back at teardown. Reading
        # the SAVEPOINT's own `is_active` flag from the connection instead sidesteps
        # that hierarchy entirely and works identically after either commit or
        # rollback. This is the current recipe from SQLAlchemy's own docs ("Joining a
        # Session into an External Transaction (such as for test suites)").
        nonlocal nested
        if not nested.is_active:
            session.expire_all()
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()
