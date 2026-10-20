from __future__ import annotations

from typing import Any

# Account roles used by the API until a roles table is introduced.
_ROLES: tuple[dict[str, str], ...] = (
    {"name": "user", "description": "Can upload documents and query their own library."},
    {"name": "admin", "description": "Can reconcile storage and inspect operational endpoints."},
)


def list_roles() -> list[dict[str, Any]]:
    return [dict(role) for role in _ROLES]


def get_role(name: str) -> dict[str, Any] | None:
    key = name.strip().lower()
    for role in _ROLES:
        if role["name"] == key:
            return dict(role)
    return None
