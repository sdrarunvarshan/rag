from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.admin_service import reconcile_garage as reconcile
from app.services.auth_service import get_current_user

router = APIRouter(tags=["admin"])


@router.get("/admin/reconcile-garage")
def reconcile_garage(current_user: dict = Depends(get_current_user)) -> dict:
    return reconcile(current_user)
