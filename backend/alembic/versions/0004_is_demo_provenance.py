"""is demo provenance

Adds an `is_demo` boolean to `daily_metrics`, `bioage_scores`, `measurements` and
`profile` so synthetic rows written by `bioage seed-demo` are structurally
distinguishable from rows derived from a real sync. Before this, a demo row and a
parsed real one were byte-for-byte indistinguishable once written, so the only way to
separate them again was `bioage rebuild`'s all-or-nothing re-derivation from
`raw_data_points` -- a manual step a user has to remember and run. With this column,
`SyncService` can find and evict exactly the demo rows, automatically, the moment real
data starts arriving (see backend/src/bioage/ingest/sync.py's `evict_demo_data`).

`server_default=false()` means every existing row -- which, in any database that has
ever been synced with real data, is real -- defaults to `is_demo = false` without
requiring a backfill pass, and an `ALTER TABLE ... ADD COLUMN` with a constant default
does not rewrite the table on modern Postgres. `raw_data_points` intentionally has no
`is_demo` column: `seed_demo` never writes there, so every row in that table is real by
construction, which is also what `seed_demo`'s own real-data guard relies on.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'daily_metrics',
        sa.Column('is_demo', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        op.f('ix_daily_metrics_is_demo'), 'daily_metrics', ['is_demo'], unique=False
    )
    op.add_column(
        'bioage_scores',
        sa.Column('is_demo', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        op.f('ix_bioage_scores_is_demo'), 'bioage_scores', ['is_demo'], unique=False
    )
    op.add_column(
        'measurements',
        sa.Column('is_demo', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        'profile',
        sa.Column('is_demo', sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('profile', 'is_demo')
    op.drop_column('measurements', 'is_demo')
    op.drop_index(op.f('ix_bioage_scores_is_demo'), table_name='bioage_scores')
    op.drop_column('bioage_scores', 'is_demo')
    op.drop_index(op.f('ix_daily_metrics_is_demo'), table_name='daily_metrics')
    op.drop_column('daily_metrics', 'is_demo')
