"""Enums used across the data layer."""
import enum


class AssetStatus(str, enum.Enum):
    CREATED = "CREATED"
    PACKED = "PACKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RECEIVED = "RECEIVED"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class SackStatus(str, enum.Enum):
    CREATED = "CREATED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"


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
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"


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


# Valid asset status transitions
ASSET_TRANSITIONS: dict[AssetStatus, set[AssetStatus]] = {
    AssetStatus.CREATED: {AssetStatus.PACKED, AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.PACKED: {AssetStatus.CREATED, AssetStatus.IN_TRANSIT, AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.IN_TRANSIT: {AssetStatus.DELIVERED, AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.DELIVERED: {AssetStatus.RECEIVED, AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.RECEIVED: {AssetStatus.DAMAGED, AssetStatus.LOST},
    AssetStatus.DAMAGED: set(),
    AssetStatus.LOST: set(),
}

# Valid sack status transitions
SACK_TRANSITIONS: dict[SackStatus, set[SackStatus]] = {
    SackStatus.CREATED: {SackStatus.PICKED_UP},
    SackStatus.PICKED_UP: {SackStatus.IN_TRANSIT, SackStatus.DELIVERED},
    SackStatus.IN_TRANSIT: {SackStatus.DELIVERED},
    SackStatus.DELIVERED: {SackStatus.CLOSED},
    SackStatus.CLOSED: set(),
}
