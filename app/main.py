from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from temporalio.client import Client

from app import cache, db
from app.auth import (
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
    create_access_token,
    get_current_user,
    get_optional_user,
    hash_password,
    verify_password,
)
from app.config import (
    TEMPORAL_HOST,
    TEMPORAL_NAMESPACE,
    TEMPORAL_PORT,
    TEMPORAL_TASK_QUEUE,
    UPLOAD_DIR,
    ensure_data_dirs,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_UPLOAD_SIZE_MB,
)
from app.garage_client import (
    delete_document_images,
    ensure_bucket,
    get_image_bytes,
    get_image_url,
    ping as garage_ping,
)
from app.index import hybrid_index
from app.ingest import ingest_pdf
from app.langgraph_rag import run_rag_pipeline, stream_rag_pipeline
from app.telemetry import instrument_fastapi, setup_telemetry
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
    images: list[dict] = Field(default_factory=list)
    context: str
    flow: dict[str, dict]
    llm_skipped: bool = False
    query_plan: dict = Field(default_factory=dict)
    structured: list[dict] = Field(default_factory=list)


# --- Authentication Endpoints ---

@app.post("/auth/register", response_model=TokenResponse)
def register(body: UserRegister) -> TokenResponse:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    existing = db.get_user_by_email(body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists",
        )
    hashed = hash_password(body.password)
    user = db.create_user(body.email, hashed, body.full_name)
    token = create_access_token({"sub": user["id"], "email": user["email"]})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(**user),
    )


@app.post("/auth/login", response_model=TokenResponse)
def login(body: UserLogin) -> TokenResponse:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    user = db.get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": user["id"], "email": user["email"]})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            full_name=user.get("full_name"),
            created_at=user.get("created_at"),
        ),
    )


@app.get("/auth/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=current_user["id"],
        email=current_user["email"],
        full_name=current_user.get("full_name"),
        created_at=current_user.get("created_at"),
    )


# --- UI and Public Status ---

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
    status_str = "ok" if postgres and valkey and garage else "degraded"
    return {"status": status_str, "postgres": postgres, "valkey": valkey, "garage": garage}


# --- Document Endpoints (Protected) ---

@app.get("/documents")
def documents(current_user: dict = Depends(get_current_user)) -> dict:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    items = db.list_documents(UUID(current_user["id"]))
    return {"documents": items}


@app.delete("/documents/{document_id}")
def delete_document_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Delete a document completely:
    1. Removes all associated images from Garage S3 object store.
    2. Deletes the document row from PostgreSQL (cascades to nodes, images, embeddings).
    3. Rebuilds the hybrid index (BM25 + pgvector).
    """
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    try:
        doc_uuid = UUID(document_id)
        user_uuid = UUID(current_user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="document_id must be a UUID") from exc
    if not db.document_exists(doc_uuid, user_uuid):
        raise HTTPException(status_code=404, detail="document_id not found or access denied")

    # 1. Purge Garage object storage
    try:
        delete_document_images(doc_uuid)
        log.info("Deleted images from Garage for document %s", doc_uuid)
    except Exception as exc:
        log.warning("Could not delete images from Garage (Garage may be down): %s", exc)

    # 2. Delete from PostgreSQL (cascades to nodes & images)
    deleted = db.delete_document(doc_uuid, user_uuid)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete document from database")

    # 3. Rebuild the BM25 search index to remove deleted document's nodes
    try:
        hybrid_index.rebuild_bm25()
        log.info("BM25 index updated after deleting document %s", doc_uuid)
    except Exception as exc:
        log.warning("Failed to refresh hybrid index: %s", exc)

    return {
        "status": "deleted",
        "document_id": document_id,
        "message": "Document and all associated PostgreSQL and Garage data removed successfully",
    }


@app.get("/documents/{document_id}/images")
def document_images(
    document_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
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


@app.get("/images/{image_id}")
def image_file(
    image_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Serve image bytes from Garage storage. Protected by JWT."""
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    try:
        img_uuid = UUID(image_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="image_id must be a UUID") from exc
    image_meta = db.fetch_image(img_uuid)
    if not image_meta:
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        data, mime_type = get_image_bytes(image_meta["minio_key"])
        return Response(
            content=data,
            media_type=mime_type or image_meta.get("mime_type") or "image/png",
        )
    except Exception as exc:
        log.warning("Could not read image bytes from Garage: %s", exc)
        try:
            return RedirectResponse(url=get_image_url(image_meta["minio_key"]))
        except Exception:
            raise HTTPException(status_code=502, detail=f"Image storage unavailable: {exc}")


@app.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file")
    
    if file.size and file.size > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413, 
            detail=f"File exceeds maximum allowed size of {MAX_UPLOAD_SIZE_MB}MB"
        )
        
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    ensure_data_dirs()
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix=suffix, delete=False) as handle:
        payload = await file.read()
        
        # Check actual file size after reading (in case file.size was None)
        if len(payload) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413, 
                detail=f"File exceeds maximum allowed size of {MAX_UPLOAD_SIZE_MB}MB"
            )
            
        # Magic bytes validation for PDF (%PDF-)
        if not payload.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=415,
                detail="File content does not appear to be a valid PDF document"
            )
            
        handle.write(payload)
        temp_path = Path(handle.name)
    try:
        if temporal_client:
            import time
            log.info("Using Temporal workflow for ingest")
            # Use a unique workflow ID per upload to avoid conflicts with stale workflows.
            # The temp file is deleted by parse_pdf_activity after it finishes parsing.
            workflow_id = f"ingest-{Path(file.filename).stem}-{int(time.time())}"
            result = await temporal_client.execute_workflow(
                IngestWorkflow.run,
                IngestParams(pdf_path=str(temp_path), filename=file.filename, user_id=current_user["id"]),
                id=workflow_id,
                task_queue=TEMPORAL_TASK_QUEUE,
            )
        else:
            log.info("Using direct execution for ingest (Temporal unavailable)")
            result = ingest_pdf(temp_path, filename=file.filename, user_id=current_user["id"])
    except Exception as exc:
        log.exception("Ingest failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        # When using Temporal the worker deletes the file after parsing.
        # For direct execution we clean it up here.
        if not temporal_client:
            temp_path.unlink(missing_ok=True)
    return result


def _resolved_document_id(document_id: str | None, user_id: str) -> str | None:
    if not document_id:
        return None
    try:
        doc_uuid = UUID(document_id)
        user_uuid = UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="document_id must be a UUID") from exc
    if not db.document_exists(doc_uuid, user_uuid):
        raise HTTPException(status_code=404, detail="document_id not found or access denied")
    return document_id


@app.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    current_user: dict = Depends(get_current_user),
) -> QueryResponse:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    resolved_doc_id = _resolved_document_id(body.document_id, current_user["id"])

    if temporal_client:
        log.info("Using Temporal workflow for query")
        result = await temporal_client.execute_workflow(
            QueryWorkflow.run,
            QueryParams(question=body.question, document_id=resolved_doc_id),
            id=f"query-{hash(body.question)}",
            task_queue=TEMPORAL_TASK_QUEUE,
        )
        packed = {
            "answer": result["answer"],
            "cached": result["cached"],
            "sources": result["sources"],
            "images": result.get("images", []),
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


@app.post("/query/stream")
def query_stream(
    body: QueryRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Streaming SSE endpoint for real-time conversational chat response.
    Yields:
      - data: {"event": "retrieved", "sources": [...], "images": [...], ...}
      - data: {"event": "token", "text": "..."}
      - data: {"event": "done", "answer": "...", "flow": {...}, ...}
    """
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    resolved_doc_id = _resolved_document_id(body.document_id, current_user["id"])

    def event_generator():
        try:
            for event in stream_rag_pipeline(body.question, resolved_doc_id):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            log.exception("SSE streaming generation error")
            yield f"data: {json.dumps({'event': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
