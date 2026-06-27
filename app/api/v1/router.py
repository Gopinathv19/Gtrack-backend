"""Aggregate all v1 routers."""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    assets,
    auth,
    groups,
    instances,
    invites,
    locations,
    organizations,
    sacks,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(invites.router)
api_router.include_router(organizations.router)
api_router.include_router(instances.router)
api_router.include_router(groups.router)
api_router.include_router(users.router)
api_router.include_router(locations.router)
api_router.include_router(assets.router)
api_router.include_router(sacks.router)
