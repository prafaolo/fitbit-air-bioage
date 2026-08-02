"""sync run

Adds a singleton sync_run table so POST /api/sync (now run in a FastAPI background
task instead of inline -- see backend/src/bioage/api/routes_sync.py) has somewhere to
record that a run is in flight and what the last one did, for the frontend to poll via
GET /api/sync/status.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'sync_run',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('running', sa.Boolean(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_weeks_scored', sa.Integer(), nullable=True),
        sa.Column('last_reports', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.CheckConstraint('id = 1', name='ck_sync_run_singleton'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('sync_run')
