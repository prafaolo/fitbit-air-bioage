"""Proves the `db` fixture contains a `session.commit()` made by code under test.

Later tasks (FastAPI routes, the scoring pipeline) call `session.commit()` inside the
code being tested. If the fixture merely wrapped the Session around a Connection with
one open transaction, that inner commit would end the outer transaction too, and the
committed row would survive into the next test. These two tests are deliberately
order-independent: each asserts the table is empty *on entry* (proving nothing leaked
in from a prior test), regardless of which of the two pytest happens to run first.
"""

from __future__ import annotations

from datetime import date

from bioage.db.models import SyncState


def test_commit_inside_the_fixture_is_still_rolled_back_at_teardown(db):
    assert db.query(SyncState).count() == 0
    db.add(SyncState(data_type="steps", synced_through=date(2026, 7, 1)))
    db.commit()
    assert db.query(SyncState).count() == 1


def test_a_prior_tests_commit_did_not_leak_into_this_one(db):
    assert db.query(SyncState).count() == 0
