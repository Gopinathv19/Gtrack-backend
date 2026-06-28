"""Rebuild sack_status and sack_movement_action enums.

Old lifecycle:  CREATED → PICKED_UP → IN_TRANSIT → DELIVERED → CLOSED
New lifecycle:  CREATED → IN_TRANSIT → DELIVERED → RECEIVED

Postgres enum types can't be edited in-place — you cannot remove a value from
an enum and ``ALTER TYPE`` only supports ADD VALUE. So we:

1. Create new enum types with the desired set of values.
2. Backfill the existing rows by ``ALTER COLUMN ... TYPE ... USING ...`` with
   a CASE expression that maps the old values onto the new ones.
3. Drop the old enum types.
4. Reverse the same dance in ``downgrade()``.

Revision ID: 20260628_01
Revises:
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260628_01"
down_revision = None
branch_labels = None
depends_on = None


# Old set
OLD_SACK_STATUSES = ("CREATED", "PICKED_UP", "IN_TRANSIT", "DELIVERED", "CLOSED")
OLD_SACK_ACTIONS = ("CREATED", "PICKED_UP", "IN_TRANSIT", "DELIVERED", "CLOSED")

# New set
NEW_SACK_STATUSES = ("CREATED", "IN_TRANSIT", "DELIVERED", "RECEIVED")
NEW_SACK_ACTIONS = ("CREATED", "PICKED_UP", "DELIVERED", "RECEIVED")


def upgrade() -> None:
    # ---- sack_status ----------------------------------------------------
    # Create the new enum type next to the old one.
    op.execute(
        "CREATE TYPE sack_status_new AS ENUM "
        f"({', '.join([repr(v) for v in NEW_SACK_STATUSES])})"
    )

    # Migrate the column to the new type, mapping legacy values:
    #   PICKED_UP -> IN_TRANSIT  (the new "in flight" state)
    #   CLOSED    -> RECEIVED    (terminal state)
    op.execute(
        """
        ALTER TABLE sacks
        ALTER COLUMN status TYPE sack_status_new
        USING (
            CASE status::text
                WHEN 'PICKED_UP' THEN 'IN_TRANSIT'
                WHEN 'CLOSED'    THEN 'RECEIVED'
                ELSE status::text
            END
        )::sack_status_new
        """
    )

    # Drop the old type and rename the new one to take its place.
    op.execute("DROP TYPE sack_status")
    op.execute("ALTER TYPE sack_status_new RENAME TO sack_status")

    # ---- sack_movement_action ------------------------------------------
    op.execute(
        "CREATE TYPE sack_movement_action_new AS ENUM "
        f"({', '.join([repr(v) for v in NEW_SACK_ACTIONS])})"
    )

    # Map legacy actions:
    #   IN_TRANSIT -> PICKED_UP  (old code logged IN_TRANSIT when it really
    #                            meant "left the source")
    #   CLOSED     -> RECEIVED   (terminal action)
    op.execute(
        """
        ALTER TABLE sack_movements
        ALTER COLUMN action TYPE sack_movement_action_new
        USING (
            CASE action::text
                WHEN 'IN_TRANSIT' THEN 'PICKED_UP'
                WHEN 'CLOSED'     THEN 'RECEIVED'
                ELSE action::text
            END
        )::sack_movement_action_new
        """
    )

    op.execute("DROP TYPE sack_movement_action")
    op.execute("ALTER TYPE sack_movement_action_new RENAME TO sack_movement_action")


def downgrade() -> None:
    # Recreate the old sack_status enum and map back. There's no clean
    # inverse for IN_TRANSIT (it could have been PICKED_UP or IN_TRANSIT in
    # the old model) — we pick PICKED_UP because that's the role-driven
    # transition the new system actually issues.
    op.execute(
        "CREATE TYPE sack_status_old AS ENUM "
        f"({', '.join([repr(v) for v in OLD_SACK_STATUSES])})"
    )
    op.execute(
        """
        ALTER TABLE sacks
        ALTER COLUMN status TYPE sack_status_old
        USING (
            CASE status::text
                WHEN 'IN_TRANSIT' THEN 'PICKED_UP'
                WHEN 'RECEIVED'   THEN 'CLOSED'
                ELSE status::text
            END
        )::sack_status_old
        """
    )
    op.execute("DROP TYPE sack_status")
    op.execute("ALTER TYPE sack_status_old RENAME TO sack_status")

    op.execute(
        "CREATE TYPE sack_movement_action_old AS ENUM "
        f"({', '.join([repr(v) for v in OLD_SACK_ACTIONS])})"
    )
    op.execute(
        """
        ALTER TABLE sack_movements
        ALTER COLUMN action TYPE sack_movement_action_old
        USING (
            CASE action::text
                WHEN 'RECEIVED' THEN 'CLOSED'
                ELSE action::text
            END
        )::sack_movement_action_old
        """
    )
    op.execute("DROP TYPE sack_movement_action")
    op.execute("ALTER TYPE sack_movement_action_old RENAME TO sack_movement_action")
