from __future__ import annotations

from app import cache, db
from app import garage_client


def health() -> dict:
    """Liveness probe. PostgreSQL is required."""
    postgres = db.ping()
    return {
        "status": "healthy" if postgres else "unhealthy",
        "postgres": postgres,
    }


def ready() -> dict:
    """Readiness probe. Valkey and Garage are optional."""
    postgres = db.ping()
    valkey = cache.ping()
    garage = garage_client.ping()

    if not postgres:
        return {
            "status": "not_ready",
            "postgres": postgres,
            "valkey": valkey,
            "garage": garage,
            "reason": "PostgreSQL is required but unavailable",
        }

    issues = []
    if not valkey:
        issues.append("Valkey cache unavailable (optional)")
    if not garage:
        issues.append("Garage storage unavailable (optional)")

    return {
        "status": "ready",
        "postgres": postgres,
        "valkey": valkey,
        "garage": garage,
        "issues": issues if issues else None,
    }
