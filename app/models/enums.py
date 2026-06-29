"""Enums used across the data layer."""
import enum


class AssetStatus(str, enum.Enum):
    CREATED = "CREATED"
    PACKED = "PACKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RECEIVED = "RECEIVED"
    # Reverse-leg intermediate state. After a return-required asset is
    # RECEIVED (forward leg done), the sysadmin marks it
    # PACKED_FOR_RETURN to flag that it's been earmarked to go back to
    # the store. The shifting person then picks it up (→ IN_TRANSIT)
    # and the store manager confirms receipt (→ RETURNED).
    PACKED_FOR_RETURN = "PACKED_FOR_RETURN"
    # Terminal state for return-required assets (e.g. the old laptop
    # being swapped out). RECEIVED is the forward-leg terminal; RETURNED
    # is the round-trip terminal.
    RETURNED = "RETURNED"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class SackStatus(str, enum.Enum):
    """Sack lifecycle.

    CREATED → IN_TRANSIT (picked up by shifting person)
            → DELIVERED  (delivered by shifting person)
            → RECEIVED   (received by sysadmin; terminal)
    """
    CREATED = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RECEIVED = "RECEIVED"


class AssetMovementAction(str, enum.Enum):
    CREATED = "CREATED"
    PACKED = "PACKED"
    UNPACKED = "UNPACKED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RECEIVED = "RECEIVED"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class SackMovementAction(str, enum.Enum):
    CREATED = "CREATED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    RECEIVED = "RECEIVED"


class InviteStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class RoleName(str, enum.Enum):
    ORG_ADMIN = "ORG_ADMIN"
    STORE_MAINTAINER = "STORE_MAINTAINER"
    SHIFT_PERSON = "SHIFT_PERSON"
    SYSADMIN = "SYSADMIN"
    AUDITOR = "AUDITOR"


# Valid asset status transitions.
#
# Forward leg:  CREATED → PACKED → IN_TRANSIT → DELIVERED → RECEIVED
# Return leg (only for assets where ``requires_return = True``):
#               RECEIVED → PACKED_FOR_RETURN → IN_TRANSIT → RETURNED
#
# Notes:
# - RECEIVED is the forward-leg terminal for "no return needed" assets,
#   and a *junction* state for "return required" assets: from here the
#   sysadmin can either close them out, or kick off the reverse leg by
#   moving them to PACKED_FOR_RETURN.
# - PACKED_FOR_RETURN → IN_TRANSIT is the shift-person pickup.
# - IN_TRANSIT → RETURNED is the store-manager confirmation; RETURNED
#   is the terminal state for the round trip.
# - DAMAGED / LOST are always available as exits.
ASSET_TRANSITIONS: dict[AssetStatus, set[AssetStatus]] = {
    AssetStatus.CREATED: {AssetStatus.PACKED, AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.PACKED: {AssetStatus.CREATED, AssetStatus.IN_TRANSIT, AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.IN_TRANSIT: {AssetStatus.DELIVERED, AssetStatus.RETURNED, AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.DELIVERED: {AssetStatus.RECEIVED, AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.RECEIVED: {
        AssetStatus.PACKED_FOR_RETURN,
        AssetStatus.DAMAGED,
        AssetStatus.LOST,
    },
    AssetStatus.PACKED_FOR_RETURN: {
        AssetStatus.RECEIVED,  # un-pack (sysadmin made a mistake)
        AssetStatus.IN_TRANSIT,
        AssetStatus.DAMAGED,
        AssetStatus.LOST,
    },
    AssetStatus.RETURNED: {AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.DAMAGED: set(),
    AssetStatus.LOST: set(),
}

# Valid sack status transitions
SACK_TRANSITIONS: dict[SackStatus, set[SackStatus]] = {
    SackStatus.CREATED: {SackStatus.IN_TRANSIT},
    SackStatus.IN_TRANSIT: {SackStatus.DELIVERED},
    SackStatus.DELIVERED: {SackStatus.RECEIVED},
    SackStatus.RECEIVED: set(),
}
