from __future__ import annotations

from fastapi import APIRouter

from app.services.health_service import health as health_status
from app.services.health_service import ready as ready_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return health_status()


@router.get("/ready")
def ready() -> dict:
    return ready_status()
