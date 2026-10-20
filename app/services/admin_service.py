from __future__ import annotations

import logging

from fastapi import HTTPException

log = logging.getLogger(__name__)


def reconcile_garage(current_user: dict) -> dict:
    """Find Garage objects that no longer have database metadata."""
    del current_user
    from app.garage_client import reconcile_garage_objects

    try:
        return reconcile_garage_objects()
    except Exception as exc:
        log.error("Garage reconciliation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Reconciliation failed: {str(exc)}")
