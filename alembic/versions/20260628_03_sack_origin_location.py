"""Add origin_location_id to sacks.

Complements the destination column added in 20260628_02. The origin is
where the sack starts its journey (the source warehouse / dock / desk
where the store packed it). Like the destination it's optional for
legacy rows, editable in-flight by ORG_ADMIN / STORE_MAINTAINER, and
frozen once the sack is RECEIVED.

Revision ID: 20260628_03
Revises: 20260628_02
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa


revision = "20260628_03"
down_revision = "20260628_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sacks",
        sa.Column(
            "origin_location_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sack_origin_location",
        "sacks",
        ["origin_location_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sack_origin_location", table_name="sacks")
    op.drop_column("sacks", "origin_location_id")
