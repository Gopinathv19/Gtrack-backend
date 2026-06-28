"""Invite endpoints."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_roles
from app.api.v1.endpoints.auth import _build_token_pair
from app.core.config import settings
from app.core.security import generate_invite_token, hash_password
from app.models import Group, Instance, Invite, Role, User, UserRole
from app.models.enums import InviteStatus, RoleName
from app.schemas.auth import TokenPair
from app.schemas.invite import (
    InviteAccept,
    InviteCreate,
    InviteCreatedResponse,
    InviteOut,
)
from app.schemas.user import UserOut

router = APIRouter(prefix="/invites", tags=["invites"])


@router.post("", response_model=InviteCreatedResponse, status_code=201)
def create_invite(
    payload: InviteCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    g = db.get(Group, payload.group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    inst = db.get(Instance, g.instance_id)
    if not inst or inst.organization_id != me.organization_id:
        raise HTTPException(404, "Group not found")
    role = db.get(Role, payload.role_id)
    if not role:
        raise HTTPException(404, "Role not found")

    token = generate_invite_token()
    invite = Invite(
        token=token,
        email=payload.email,
        organization_id=me.organization_id,
        group_id=payload.group_id,
        role_id=payload.role_id,
        invited_by=me.id,
        status=InviteStatus.PENDING,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.INVITE_EXPIRE_HOURS),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    # TODO: send email here. For now we just return the token.
    return InviteCreatedResponse(
        invite_id=invite.id,
        token=token,
        accept_url=f"{settings.INVITE_BASE_URL}?token={token}",
    )


@router.post("/accept", response_model=TokenPair, status_code=201)
def accept_invite(
    response: Response,
    payload: InviteAccept,
    token: str = Query(..., description="Invite token from the accept URL"),
    db: Session = Depends(get_db),
):
    """Accept an invite and log the user in.

    The ``token`` is read from the query string (matching the URL embedded in
    the invite email), and credentials/name come from the JSON body. On
    success we issue a fresh access + refresh token pair so the new member
    lands in the app already authenticated.
    """
    invite = db.query(Invite).filter(Invite.token == token).one_or_none()
    if not invite:
        raise HTTPException(404, "Invalid invite token")
    if invite.status != InviteStatus.PENDING:
        raise HTTPException(400, f"Invite is {invite.status.value}")
    if invite.expires_at < datetime.now(timezone.utc):
        invite.status = InviteStatus.EXPIRED
        db.commit()
        raise HTTPException(400, "Invite expired")

    # Find or create user
    user = db.query(User).filter(User.email == invite.email).one_or_none()
    if user is None:
        user = User(
            email=invite.email,
            name=payload.name,
            organization_id=invite.organization_id,
            hashed_password=hash_password(payload.password),
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        # Existing account (e.g. someone registered first, then opened the
        # invite link). Attach them to the inviting org if they have none,
        # otherwise reject cross-org conflicts instead of silently
        # overwriting their tenant.
        if user.organization_id is None:
            user.organization_id = invite.organization_id
        elif user.organization_id != invite.organization_id:
            raise HTTPException(
                400,
                "This email already belongs to another organization.",
            )
        if payload.name:
            user.name = payload.name
        user.hashed_password = hash_password(payload.password)
        user.is_active = True

    # Assign role in group
    existing = (
        db.query(UserRole)
        .filter(
            UserRole.user_id == user.id,
            UserRole.role_id == invite.role_id,
            UserRole.group_id == invite.group_id,
        )
        .first()
    )
    if not existing:
        db.add(UserRole(user_id=user.id, role_id=invite.role_id, group_id=invite.group_id))

    invite.status = InviteStatus.ACCEPTED
    invite.accepted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    # Auto-login: issue an access token + set refresh cookie so the client
    # can drop straight into the dashboard.
    return _build_token_pair(db, user, response)


@router.post("/{invite_id}/resend", status_code=status.HTTP_204_NO_CONTENT)
def resend_invite(
    invite_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    invite = db.get(Invite, invite_id)
    if not invite or invite.organization_id != me.organization_id:
        raise HTTPException(404, "Invite not found")
    if invite.status != InviteStatus.PENDING:
        raise HTTPException(400, "Only pending invites can be resent")
    invite.expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.INVITE_EXPIRE_HOURS
    )
    db.commit()
    # TODO: send email
    return None


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(
    invite_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    invite = db.get(Invite, invite_id)
    if not invite or invite.organization_id != me.organization_id:
        raise HTTPException(404, "Invite not found")
    invite.status = InviteStatus.REVOKED
    db.commit()
    return None


@router.get("", response_model=list[InviteOut])
def list_invites(
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    return (
        db.query(Invite)
        .filter(Invite.organization_id == me.organization_id)
        .order_by(Invite.created_at.desc())
        .all()
    )
