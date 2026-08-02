"""raw data point payload hash

Discriminates RawDataPoint rows by a hash of their payload, not just (data_type,
point_date). Without this, every payload a parser returns None for falls back to being
keyed on (data_type, window.start) alone -- so many distinct unparseable payloads in one
sync window collide on that single key and only the last one written survives, silently
losing up to 90 days of archive. See backend/src/bioage/ingest/sync.py's module
docstring and backend/src/bioage/db/models.py's RawDataPoint docstring.

This also makes the `expected_empty` early-skip in sync.py unnecessary (removed in the
same change): every fetched payload can now be archived unconditionally, so
`daily-vo2-max`'s points_stored reflects what was actually fetched instead of being
structurally pinned at 0.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('uq_raw_type_date', 'raw_data_points', type_='unique')
    # Nullable at first so the column can be backfilled on a table that already has
    # rows; there are none in any deployment of this project today; the backfill below
    # exists so this migration is still correct if that ever changes.
    op.add_column(
        'raw_data_points', sa.Column('payload_hash', sa.String(length=64), nullable=True)
    )
    # Backfill with a hash of the existing payload. This does not need to match the
    # application's own hash function (sha256 of canonical JSON, see
    # bioage.ingest.sync._payload_hash) bit-for-bit -- it only has to be *some* stable,
    # collision-resistant value so existing rows satisfy the new NOT NULL + unique
    # constraint below. Postgres's built-in md5() needs no extension, unlike sha256
    # (pgcrypto).
    op.execute(
        "UPDATE raw_data_points SET payload_hash = md5(payload::text) "
        "WHERE payload_hash IS NULL"
    )
    op.alter_column('raw_data_points', 'payload_hash', nullable=False)
    op.create_unique_constraint(
        'uq_raw_type_date_hash', 'raw_data_points', ['data_type', 'point_date', 'payload_hash']
    )


def downgrade() -> None:
    """Downgrade schema.

    Note: if any (data_type, point_date) pair has accumulated more than one row under
    the wider hash-discriminated constraint (the whole point of this migration), this
    downgrade's `create_unique_constraint` will fail -- that data genuinely no longer
    fits the narrower pre-migration schema. There is no data-destroying way to make it
    fit that this migration should silently choose on your behalf; resolve the
    duplicates (e.g. keep only the newest `ingested_at` per pair) before downgrading.
    """
    op.drop_constraint('uq_raw_type_date_hash', 'raw_data_points', type_='unique')
    op.drop_column('raw_data_points', 'payload_hash')
    op.create_unique_constraint('uq_raw_type_date', 'raw_data_points', ['data_type', 'point_date'])
