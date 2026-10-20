from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas.auth import TokenResponse, UserLogin, UserRegister, UserResponse
from app.services.auth_service import get_current_user, login_user, register_user, to_user_response

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(body: UserRegister) -> TokenResponse:
    return register_user(body)


@router.post("/login", response_model=TokenResponse)
def login(body: UserLogin) -> TokenResponse:
    return login_user(body)


@router.get("/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    return to_user_response(current_user)
