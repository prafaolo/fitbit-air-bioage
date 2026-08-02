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
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(session: Session, transaction: object) -> None:
        # `transaction.nested` is True for both the SAVEPOINT itself and for the
        # session's own "sessionless" transaction wrapping it; only restart when the
        # SAVEPOINT proper has ended (i.e. its parent is not itself nested).
        if transaction.nested and not transaction._parent.nested:  # type: ignore[attr-defined]
            session.expire_all()
            session.begin_nested()

    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()
