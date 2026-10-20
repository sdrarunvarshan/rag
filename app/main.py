from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse

from app import cache, db
from app.api.v1.router import build_v1_router
from app.config import TEMPORAL_HOST, TEMPORAL_NAMESPACE, TEMPORAL_PORT, ensure_data_dirs
from app.core import runtime
from app.errors import (
    general_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.garage_client import ensure_bucket
from app.garage_client import ping as garage_ping
from app.index import hybrid_index
from app.middleware import RequestIDMiddleware, add_cors_middleware
from app.services.admin_service import reconcile_garage
from app.services.document_service import delete_document_endpoint
from app.services.health_service import health, ready
from app.services.ingest_service import ingest
from app.telemetry import instrument_fastapi, setup_telemetry
from temporalio.client import Client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

UI_PAGE = Path(__file__).resolve().parent / "templates" / "index.html"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_data_dirs()

    try:
        setup_telemetry()
        log.info("OpenTelemetry tracing enabled with Phoenix")
    except Exception as exc:
        log.warning("Telemetry setup failed: %s", exc)

    try:
        db.init_schema()
        if not db.check_alembic_migration():
            log.error(
                "Database schema is not up to date. "
                "Please run: uv run alembic upgrade head"
            )
            raise RuntimeError(
                "Database schema migration required. "
                "Run 'uv run alembic upgrade head' before starting the application."
            )
        log.info("Postgres schema ready")
    except Exception as exc:
        log.error("Postgres schema initialization failed: %s", exc)
        raise
    if cache.ping():
        log.info("Valkey reachable")
    else:
        log.warning("Valkey unavailable at startup")
    try:
        ensure_bucket()
        if garage_ping():
            log.info("Garage reachable")
        else:
            log.warning("Garage unavailable at startup")
    except Exception as exc:
        log.warning("Garage setup failed: %s", exc)
    try:
        db.ping()
        hybrid_index.load_or_rebuild()
    except Exception as exc:
        log.warning("Index load skipped: %s", exc)

    try:
        runtime.temporal_client = await Client.connect(
            f"{TEMPORAL_HOST}:{TEMPORAL_PORT}",
            namespace=TEMPORAL_NAMESPACE,
        )
        log.info("Connected to Temporal at %s:%s", TEMPORAL_HOST, TEMPORAL_PORT)
    except Exception as exc:
        log.warning("Temporal unavailable, falling back to direct execution: %s", exc)
        runtime.temporal_client = None

    yield

    if runtime.temporal_client:
        runtime.temporal_client.close()
        runtime.temporal_client = None


app = FastAPI(title="Chunkless Structured RAG", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
add_cors_middleware(app)
instrument_fastapi(app)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Existing clients call /auth, /query, /documents. /api/v1 exposes the same routers.
app.include_router(build_v1_router())
app.include_router(build_v1_router(), prefix="/api/v1")


@app.get("/")
def home():
    if not UI_PAGE.is_file():
        raise HTTPException(
            status_code=500,
            detail="UI file missing: app/templates/index.html. API docs are at /docs",
        )
    return FileResponse(UI_PAGE, media_type="text/html")


__all__ = [
    "app",
    "delete_document_endpoint",
    "health",
    "ingest",
    "ready",
    "reconcile_garage",
]
