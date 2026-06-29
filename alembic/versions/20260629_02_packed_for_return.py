"""Add PACKED_FOR_RETURN value to asset_status enum.

The asset return leg uses three distinct states:

    RECEIVED  →  PACKED_FOR_RETURN  →  IN_TRANSIT  →  RETURNED

  * Sysadmin marks the asset PACKED_FOR_RETURN once they've identified
    that the old asset has to go back.
  * Shift person picks it up — moves it to IN_TRANSIT.
  * Store manager receives the returned asset — moves it to RETURNED
    (terminal).

This migration only adds the new enum value; the actual transition
matrix lives in ``app/models/enums.py``.

Revision ID: 20260629_02
Revises: 20260629_01
Create Date: 2026-06-29
"""
from alembic import op


revision = "20260629_02"
down_revision = "20260629_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE asset_status ADD VALUE IF NOT EXISTS 'PACKED_FOR_RETURN'"
        )


def downgrade() -> None:
    # Postgres doesn't support removing a value from an enum without a
    # full type rebuild — and the column may already have rows in this
    # state. Safest no-op.
    pass
