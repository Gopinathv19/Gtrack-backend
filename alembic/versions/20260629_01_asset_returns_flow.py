"""Add return-of-asset flow.

Adds:
- ``assets.requires_return`` (bool, default false) — set by the store
  manager when the asset will need to come back (e.g. swapping a user's
  old laptop with a new one).
- ``RETURNED`` value to the ``asset_status`` enum — terminal state for
  return-required assets once they make it back to the store.

Sack lifecycle (ACTIVE / PENDING_RETURN / CLOSED) is derived from these
columns server-side, so no new sack column is needed.

Revision ID: 20260629_01
Revises: 20260628_03
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa


revision = "20260629_01"
down_revision = "20260628_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) New nullable column with a server default so existing rows are
    # backfilled cleanly. We drop the server default afterwards so the
    # application layer becomes the source of truth.
    op.add_column(
        "assets",
        sa.Column(
            "requires_return",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("assets", "requires_return", server_default=None)

    # 2) Extend the asset_status enum with the new RETURNED value.
    # Postgres requires this be done outside a transaction block for
    # older versions; alembic's autocommit_block handles that.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE asset_status ADD VALUE IF NOT EXISTS 'RETURNED'")


def downgrade() -> None:
    # Note: Postgres has no native "remove enum value" — leaving the
    # RETURNED value in place is the safe choice. We only drop the column.
    op.drop_column("assets", "requires_return")
