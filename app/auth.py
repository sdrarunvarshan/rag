"""Authentication helpers. Implementation lives in app.services.auth_service."""

from app.schemas.auth import TokenResponse, UserLogin, UserRegister, UserResponse
from app.services.auth_service import (
    create_access_token,
    decode_access_token,
    get_current_user,
    get_optional_user,
    hash_password,
    login_user,
    register_user,
    security,
    verify_password,
)

__all__ = [
    "TokenResponse",
    "UserLogin",
    "UserRegister",
    "UserResponse",
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "get_optional_user",
    "hash_password",
    "login_user",
    "register_user",
    "security",
    "verify_password",
]
