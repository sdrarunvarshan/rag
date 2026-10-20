from __future__ import annotations

from fastapi import HTTPException

from app.repositories.role_repository import get_role, list_roles
from app.schemas.role import RoleResponse


def list_role_catalog() -> list[RoleResponse]:
    return [RoleResponse(**role) for role in list_roles()]


def get_role_catalog_entry(name: str) -> RoleResponse:
    role = get_role(name)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return RoleResponse(**role)
