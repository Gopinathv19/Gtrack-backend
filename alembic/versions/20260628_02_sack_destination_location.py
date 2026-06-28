"""Add destination_location_id to sacks.

The store assigns the *intended* drop-off location for a sack at creation
time. This destination is editable later (even while the sack is in
transit) — but only by ORG_ADMIN or STORE_MAINTAINER, and only while the
sack hasn't been RECEIVED yet. That policy is enforced in the API layer;
the schema change here just makes room for the data.

Revision ID: 20260628_02
Revises: 20260628_01
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa


revision = "20260628_02"
down_revision = "20260628_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sacks",
        sa.Column(
            "destination_location_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sack_destination_location",
        "sacks",
        ["destination_location_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sack_destination_location", table_name="sacks")
    op.drop_column("sacks", "destination_location_id")
