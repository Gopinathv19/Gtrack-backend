"""SQLAlchemy ORM models for Gtrack multi-tenant asset tracking."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base_class import Base
from app.models.enums import (
    AssetStatus,
    SackStatus,
    AssetMovementAction,
    SackMovementAction,
    InviteStatus,
)


# ---------- Mixins ----------
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------- Organization Hierarchy ----------
class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    instances: Mapped[list["Instance"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(back_populates="organization")
    assets: Mapped[list["Asset"]] = relationship(back_populates="organization")


class Instance(Base, TimestampMixin):
    __tablename__ = "instances"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_instance_org_name"),
        Index("ix_instance_org", "organization_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    organization: Mapped["Organization"] = relationship(back_populates="instances")
    groups: Mapped[list["Group"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan"
    )


class Group(Base, TimestampMixin):
    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("instance_id", "name", name="uq_group_instance_name"),
        Index("ix_group_instance", "instance_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    instance_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    instance: Mapped["Instance"] = relationship(back_populates="groups")
    locations: Mapped[list["Location"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    user_roles: Mapped[list["UserRole"]] = relationship(back_populates="group")
    assets: Mapped[list["Asset"]] = relationship(back_populates="group")


# ---------- Users / RBAC ----------
class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (Index("ix_user_org", "organization_id"),)

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Nullable: a user can register without an organization and later
    # create or be invited to one.
    organization_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Optional Supabase Auth linkage
    supabase_user_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="users")
    user_roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    user_roles: Mapped[list["UserRole"]] = relationship(back_populates="role")


class UserRole(Base, TimestampMixin):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "group_id", name="uq_userrole_user_role_group"),
        Index("ix_userrole_user", "user_id"),
        Index("ix_userrole_group", "group_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="user_roles")
    role: Mapped["Role"] = relationship(back_populates="user_roles")
    group: Mapped["Group"] = relationship(back_populates="user_roles")


# ---------- Invites ----------
class Invite(Base, TimestampMixin):
    __tablename__ = "invites"
    __table_args__ = (Index("ix_invite_email", "email"),)

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    invited_by: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    status: Mapped[InviteStatus] = mapped_column(
        SAEnum(InviteStatus, name="invite_status"), nullable=False, default=InviteStatus.PENDING
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- Refresh tokens ----------
class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_user", "user_id"),)

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    replaced_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


# ---------- Locations ----------
class Location(Base, TimestampMixin):
    __tablename__ = "locations"
    __table_args__ = (Index("ix_location_group", "group_id"),)

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    building: Mapped[str | None] = mapped_column(String(255))
    floor: Mapped[str | None] = mapped_column(String(50))
    room: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)

    group: Mapped["Group"] = relationship(back_populates="locations")


# ---------- Assets ----------
class Asset(Base, TimestampMixin):
    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_asset_org_inst_grp", "organization_id", "instance_id", "group_id"),
        Index("ix_asset_location", "current_location_id"),
        Index("ix_asset_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    ticket_id: Mapped[str] = mapped_column(String(6), nullable=False, unique=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(100), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    instance_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    current_location_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[AssetStatus] = mapped_column(
        SAEnum(AssetStatus, name="asset_status"), nullable=False, default=AssetStatus.CREATED
    )
    created_by: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Optimistic concurrency
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}

    organization: Mapped["Organization"] = relationship(back_populates="assets")
    group: Mapped["Group"] = relationship(back_populates="assets")
    movements: Mapped[list["AssetMovement"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    sack_assets: Mapped[list["SackAsset"]] = relationship(back_populates="asset")


# ---------- Sacks ----------
class Sack(Base, TimestampMixin):
    __tablename__ = "sacks"
    __table_args__ = (
        Index("ix_sack_status", "status"),
        Index("ix_sack_origin_location", "origin_location_id"),
        Index("ix_sack_destination_location", "destination_location_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    sack_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[SackStatus] = mapped_column(
        SAEnum(SackStatus, name="sack_status"), nullable=False, default=SackStatus.CREATED
    )
    # Origin / source location — where the sack starts its journey.
    # Assigned by the store at creation time and editable in-flight by
    # ORG_ADMIN / STORE_MAINTAINER via ``/sacks/{id}/origin``.
    origin_location_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )
    # Intended drop-off location. Assigned by the store at creation time
    # and editable in-flight by ORG_ADMIN / STORE_MAINTAINER (see
    # ``/sacks/{id}/destination``). Nullable because legacy rows predate
    # the field.
    destination_location_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}

    sack_assets: Mapped[list["SackAsset"]] = relationship(
        back_populates="sack", cascade="all, delete-orphan"
    )
    movements: Mapped[list["SackMovement"]] = relationship(
        back_populates="sack", cascade="all, delete-orphan"
    )


class SackAsset(Base):
    __tablename__ = "sack_assets"
    __table_args__ = (
        UniqueConstraint("sack_id", "asset_id", name="uq_sack_asset"),
        Index("ix_sackasset_sack", "sack_id"),
        Index("ix_sackasset_asset", "asset_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    sack_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sacks.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    packed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    packed_by: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    sack: Mapped["Sack"] = relationship(back_populates="sack_assets")
    asset: Mapped["Asset"] = relationship(back_populates="sack_assets")


# ---------- Movements ----------
class AssetMovement(Base):
    __tablename__ = "asset_movements"
    __table_args__ = (
        Index("ix_assetmove_asset", "asset_id"),
        Index("ix_assetmove_sack", "sack_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    sack_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sacks.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[AssetMovementAction] = mapped_column(
        SAEnum(AssetMovementAction, name="asset_movement_action"), nullable=False
    )
    performed_by: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    from_location_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    to_location_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    asset: Mapped["Asset"] = relationship(back_populates="movements")


class SackMovement(Base):
    __tablename__ = "sack_movements"
    __table_args__ = (Index("ix_sackmove_sack", "sack_id"),)

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    sack_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sacks.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[SackMovementAction] = mapped_column(
        SAEnum(SackMovementAction, name="sack_movement_action"), nullable=False
    )
    performed_by: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    from_location_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    to_location_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    remarks: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sack: Mapped["Sack"] = relationship(back_populates="movements")


# ---------- Audit Log ----------
class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_user", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    organization_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
