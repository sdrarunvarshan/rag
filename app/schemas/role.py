from __future__ import annotations

from pydantic import BaseModel


class RoleResponse(BaseModel):
    name: str
    description: str
