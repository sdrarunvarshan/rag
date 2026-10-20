from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas.role import RoleResponse
from app.services.auth_service import get_current_user
from app.services.role_service import get_role_catalog_entry, list_role_catalog

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("", response_model=list[RoleResponse])
def roles(_current_user: dict = Depends(get_current_user)) -> list[RoleResponse]:
    return list_role_catalog()


@router.get("/{name}", response_model=RoleResponse)
def role(name: str, _current_user: dict = Depends(get_current_user)) -> RoleResponse:
    return get_role_catalog_entry(name)
