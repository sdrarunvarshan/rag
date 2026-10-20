from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas.auth import UserResponse
from app.services.auth_service import get_current_user, to_user_response

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def current_user_profile(current_user: dict = Depends(get_current_user)) -> UserResponse:
    return to_user_response(current_user)
