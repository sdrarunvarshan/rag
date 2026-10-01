from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from temporalio.client import Client

from app import cache, db
from app.config import (
    TEMPORAL_HOST,
    TEMPORAL_NAMESPACE,
    TEMPORAL_PORT,
    TEMPORAL_TASK_QUEUE,
    UPLOAD_DIR,
    ensure_data_dirs,
)
from app.index import hybrid_index
from app.ingest import ingest_pdf
from app.garage_client import ensure_bucket, ping as garage_ping
from app.langgraph_rag import run_rag_pipeline
from app.telemetry import setup_telemetry, instrument_fastapi
from app.temporal_workflows import IngestParams, IngestWorkflow, QueryParams, QueryWorkflow

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

UI_PAGE = Path(__file__).resolve().parent / "templates" / "index.html"

# Temporal client (initialized at startup)
temporal_client: Client | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global temporal_client
    ensure_data_dirs()

    # Set up OpenTelemetry with Phoenix
    try:
        setup_telemetry()
        log.info("OpenTelemetry tracing enabled with Phoenix")
    except Exception as exc:
        log.warning("Telemetry setup failed: %s", exc)

    try:
        db.init_schema()
        log.info("Postgres schema ready")
    except Exception as exc:
        log.warning("Postgres unavailable at startup: %s", exc)
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

    # Connect to Temporal
    try:
        temporal_client = await Client.connect(
            f"{TEMPORAL_HOST}:{TEMPORAL_PORT}",
            namespace=TEMPORAL_NAMESPACE,
        )
        log.info(f"Connected to Temporal at {TEMPORAL_HOST}:{TEMPORAL_PORT}")
    except Exception as exc:
        log.warning("Temporal unavailable, falling back to direct execution: %s", exc)
        temporal_client = None

    yield

    # Cleanup
    if temporal_client:
        temporal_client.close()


app = FastAPI(title="Chunkless Structured RAG", lifespan=lifespan)

# Instrument FastAPI with OpenTelemetry
instrument_fastapi(app)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    document_id: str | None = None


class QueryResponse(BaseModel):
    answer: str
    cached: bool
    sources: list[dict]
    context: str
    flow: dict[str, dict]
    llm_skipped: bool = False
    query_plan: dict = Field(default_factory=dict)
    structured: list[dict] = Field(default_factory=list)


@app.get("/")
def home():
    if not UI_PAGE.is_file():
        raise HTTPException(
            status_code=500,
            detail="UI file missing: app/templates/index.html. API docs are at /docs",
        )
    return FileResponse(UI_PAGE, media_type="text/html")


@app.get("/health")
def health() -> dict:
    postgres = db.ping()
    valkey = cache.ping()
    garage = garage_ping()
    status = "ok" if postgres and valkey and garage else "degraded"
    return {"status": status, "postgres": postgres, "valkey": valkey, "garage": garage}


@app.get("/documents")
def documents() -> dict:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    items = db.list_documents()
    return {"documents": items}


@app.get("/documents/{document_id}/images")
def document_images(document_id: str) -> dict:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    try:
        doc_uuid = UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="document_id must be a UUID") from exc
    if not db.document_exists(doc_uuid):
        raise HTTPException(status_code=404, detail="document_id not found")
    images = db.fetch_images_by_document(doc_uuid)
    return {"document_id": document_id, "images": images}


@app.post("/ingest")
async def ingest(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file")
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    ensure_data_dirs()
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix=suffix, delete=False) as handle:
        payload = await file.read()
        handle.write(payload)
        temp_path = Path(handle.name)
    try:
        # Use Temporal workflow if available, otherwise fall back to direct execution
        if temporal_client:
            log.info("Using Temporal workflow for ingest")
            result = await temporal_client.execute_workflow(
                IngestWorkflow.run,
                IngestParams(pdf_path=str(temp_path), filename=file.filename),
                id=f"ingest-{file.filename}",
                task_queue=TEMPORAL_TASK_QUEUE,
            )
        else:
            log.info("Using direct execution for ingest (Temporal unavailable)")
            result = ingest_pdf(temp_path, filename=file.filename)
    except Exception as exc:
        log.exception("Ingest failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return result


def _resolved_document_id(document_id: str | None) -> str | None:
    if not document_id:
        return None
    try:
        doc_uuid = UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="document_id must be a UUID") from exc
    if not db.document_exists(doc_uuid):
        raise HTTPException(status_code=404, detail="document_id not found")
    return document_id


@app.post("/query", response_model=QueryResponse)
async def query(body: QueryRequest) -> QueryResponse:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    resolved_doc_id = _resolved_document_id(body.document_id)

    # Use Temporal workflow if available, otherwise fall back to direct execution
    if temporal_client:
        log.info("Using Temporal workflow for query")
        result = await temporal_client.execute_workflow(
            QueryWorkflow.run,
            QueryParams(question=body.question, document_id=resolved_doc_id),
            id=f"query-{hash(body.question)}",
            task_queue=TEMPORAL_TASK_QUEUE,
        )
        # Format Temporal result to match QueryResponse
        packed = {
            "answer": result["answer"],
            "cached": result["cached"],
            "sources": result["sources"],
            "context": result["context"],
            "flow": result["flow"],
            "llm_skipped": result["llm_skipped"],
            "query_plan": result["query_plan"],
            "structured": result["structured"],
        }
    else:
        log.info("Using direct execution for query (Temporal unavailable)")
        packed = run_rag_pipeline(body.question, resolved_doc_id)

    return QueryResponse(**packed)
