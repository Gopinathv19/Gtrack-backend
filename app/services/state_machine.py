"""State machine validators."""
from fastapi import HTTPException

from app.models.enums import (
    ASSET_TRANSITIONS,
    AssetStatus,
    SACK_TRANSITIONS,
    SackStatus,
)


def validate_asset_transition(current: AssetStatus, target: AssetStatus) -> None:
    if target not in ASSET_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid asset status transition: {current.value} -> {target.value}",
        )


def validate_sack_transition(current: SackStatus, target: SackStatus) -> None:
    if target not in SACK_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid sack status transition: {current.value} -> {target.value}",
        )
