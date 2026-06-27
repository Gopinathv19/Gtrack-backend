"""Seed the roles table with the well-known roles."""
from app.db.session import SessionLocal
from app.models import Role
from app.models.enums import RoleName

ROLE_DESCRIPTIONS = {
    RoleName.ORG_ADMIN: "Manages organization: create instances/groups/users",
    RoleName.STORE_MAINTAINER: "Registers assets, packs them into sacks",
    RoleName.SHIFT_PERSON: "Transports sacks between locations",
    RoleName.SYSADMIN: "Receives delivered assets at final location",
    RoleName.AUDITOR: "Read-only access for audit/logging",
}


def main() -> None:
    db = SessionLocal()
    try:
        for r in RoleName:
            existing = db.query(Role).filter(Role.name == r.value).one_or_none()
            if not existing:
                db.add(Role(name=r.value, description=ROLE_DESCRIPTIONS[r]))
                print(f"Created role {r.value}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
