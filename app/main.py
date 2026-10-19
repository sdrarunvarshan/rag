from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID
from fastapi.exceptions import RequestValidationError
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from temporalio.client import Client

from app import db, cache
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
from app.errors import (
    general_exception_handler,
    http_exception_handler,
    validation_exception_handler,
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
from app.middleware import add_cors_middleware, stream_upload_to_disk, RequestIDMiddleware
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
        # Check if Alembic migrations are up to date
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

# Add request ID middleware (must be first)
app.add_middleware(RequestIDMiddleware)

# Add CORS middleware
add_cors_middleware(app)

# Instrument FastAPI with OpenTelemetry
instrument_fastapi(app)

# Add exception handlers for safe error responses
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)


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
    """
    Health check endpoint - liveness probe.
    Returns basic health status without strict dependency checks.
    """
    postgres = db.ping()
    return {
        "status": "healthy" if postgres else "unhealthy",
        "postgres": postgres,
    }


@app.get("/ready")
def ready() -> dict:
    """
    Readiness probe - checks required dependencies.
    Returns unhealthy if required dependencies (PostgreSQL) are unavailable.
    Optional dependencies (Valkey, Garage) are reported but don't fail readiness.
    """
    postgres = db.ping()
    valkey = cache.ping()
    garage = garage_ping()
    
    # PostgreSQL is required
    if not postgres:
        return {
            "status": "not_ready",
            "postgres": postgres,
            "valkey": valkey,
            "garage": garage,
            "reason": "PostgreSQL is required but unavailable",
        }
    
    # Valkey and Garage are optional for readiness
    status_str = "ready"
    issues = []
    if not valkey:
        issues.append("Valkey cache unavailable (optional)")
    if not garage:
        issues.append("Garage storage unavailable (optional)")
    
    return {
        "status": status_str,
        "postgres": postgres,
        "valkey": valkey,
        "garage": garage,
        "issues": issues if issues else None,
    }


@app.get("/admin/reconcile-garage")
def reconcile_garage(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Reconcile Garage objects with database metadata to find orphaned objects.
    
    This endpoint identifies objects in Garage that no longer have corresponding
    database entries (orphaned objects) and returns statistics.
    """
    from app.garage_client import reconcile_garage_objects
    
    try:
        result = reconcile_garage_objects()
        return result
    except Exception as exc:
        log.error("Garage reconciliation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Reconciliation failed: {str(exc)}")


# --- Document Endpoints (Protected) ---

@app.get("/documents")
def documents(current_user: dict = Depends(get_current_user)) -> dict:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    items = db.list_documents(UUID(current_user["id"]))
    return {"documents": items}


@app.get("/query-history")
def query_history(
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Fetch query history for the authenticated user."""
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    user_uuid = UUID(current_user["id"])
    history = db.fetch_query_history(user_uuid, limit=limit)
    return {"history": history}


@app.delete("/query-history/{query_id}")
def delete_query_history(
    query_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete a query from history (only if it belongs to the user)."""
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    try:
        query_uuid = UUID(query_id)
        user_uuid = UUID(current_user["id"])
        deleted = db.delete_query_history(query_uuid, user_uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Query not found or access denied")
        return {"deleted": True}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query ID")


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
    4. Invalidates cached retrieval results for the user.
    
    Returns partial-failure status if Garage deletion fails.
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

    garage_deleted = False
    db_deleted = False
    index_rebuilt = False
    cache_invalidated = False
    errors = []

    # 1. Purge Garage object storage
    try:
        delete_document_images(doc_uuid)
        garage_deleted = True
        log.info("Deleted images from Garage for document %s", doc_uuid)
    except Exception as exc:
        log.error("Failed to delete images from Garage: %s", exc)
        errors.append(f"Garage deletion failed: {str(exc)}")

    # 2. Delete from PostgreSQL (cascades to nodes & images)
    try:
        deleted = db.delete_document(doc_uuid, user_uuid)
        if not deleted:
            errors.append("Failed to delete document from database")
        else:
            db_deleted = True
            log.info("Deleted document %s from database", doc_uuid)
    except Exception as exc:
        log.error("Failed to delete document from database: %s", exc)
        errors.append(f"Database deletion failed: {str(exc)}")

    # 3. Rebuild the BM25 search index to remove deleted document's nodes
    if db_deleted:
        try:
            hybrid_index.rebuild_bm25()
            index_rebuilt = True
            log.info("BM25 index updated after deleting document %s", doc_uuid)
        except Exception as exc:
            log.warning("Failed to refresh hybrid index: %s", exc)
            errors.append(f"Index rebuild failed: {str(exc)}")

    # 4. Invalidate cached retrieval results for the user
    if db_deleted:
        try:
            cache.invalidate_user_cache(str(user_uuid))
            cache_invalidated = True
            log.info("Invalidated cache for user %s after deleting document %s", user_uuid, doc_uuid)
        except Exception as exc:
            log.warning("Failed to invalidate user cache: %s", exc)
            errors.append(f"Cache invalidation failed: {str(exc)}")

    # Determine response status
    if not db_deleted:
        raise HTTPException(
            status_code=500,
            detail=f"Critical failure: {errors[0] if errors else 'Unknown error'}"
        )
    
    if not garage_deleted:
        return {
            "status": "partial_failure",
            "document_id": document_id,
            "db_deleted": db_deleted,
            "garage_deleted": garage_deleted,
            "index_rebuilt": index_rebuilt,
            "cache_invalidated": cache_invalidated,
            "errors": errors,
            "message": "Document deleted from database but Garage objects may remain. Use reconciliation endpoint to clean up.",
        }
    
    return {
        "status": "deleted",
        "document_id": document_id,
        "db_deleted": db_deleted,
        "garage_deleted": garage_deleted,
        "index_rebuilt": index_rebuilt,
        "cache_invalidated": cache_invalidated,
        "errors": errors if errors else None,
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
        user_uuid = UUID(current_user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="document_id must be a UUID") from exc
    if not db.document_exists(doc_uuid, user_uuid):
        raise HTTPException(status_code=404, detail="document_id not found or access denied")
    images = db.fetch_images_by_document(doc_uuid, user_uuid)
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
        user_uuid = UUID(current_user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="image_id must be a UUID") from exc
    image_meta = db.fetch_image(img_uuid, user_uuid)
    if not image_meta:
        raise HTTPException(status_code=404, detail="Image not found or access denied")
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
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file")
    
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    
    request_id = getattr(request.state, "request_id", "unknown")
    
    # Stream upload to disk with size validation
    try:
        temp_path = await stream_upload_to_disk(file, MAX_UPLOAD_SIZE_BYTES)
    except HTTPException:
        # Re-raise HTTP exceptions (size limit, invalid PDF, etc.)
        raise
    except Exception as exc:
        log.exception("Upload streaming failed, request_id=%s", request_id)
        raise HTTPException(status_code=500, detail=f"Failed to process file upload: {str(exc)}") from exc
    
    # Generate stable document ID for idempotency
    from uuid import uuid4
    document_id = str(uuid4())
    
    try:
        # Upload PDF to Garage for durable storage
        from app.garage_client import upload_pdf
        pdf_bytes = temp_path.read_bytes()
        garage_key = upload_pdf(pdf_bytes, UUID(document_id), file.filename)
        
        # Clean up temp file after upload to Garage
        temp_path.unlink(missing_ok=True)
        
        if temporal_client:
            log.info("Using Temporal workflow for ingest, request_id=%s, document_id=%s", request_id, document_id)
            # Use UUID-based workflow ID to avoid collisions
            from uuid import uuid4
            workflow_id = f"ingest-{uuid4()}"
            result = await temporal_client.execute_workflow(
                IngestWorkflow.run,
                IngestParams(
                    garage_key=garage_key,
                    filename=file.filename,
                    user_id=current_user["id"],
                    document_id=document_id,
                ),
                id=workflow_id,
                task_queue=TEMPORAL_TASK_QUEUE,
            )
        else:
            log.info("Using direct execution for ingest (Temporal unavailable), request_id=%s, document_id=%s", request_id, document_id)
            # For direct execution, download from Garage and process
            from app.garage_client import get_image_bytes
            pdf_bytes, _ = get_image_bytes(garage_key)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                handle.write(pdf_bytes)
                direct_temp_path = Path(handle.name)
            try:
                result = ingest_pdf(direct_temp_path, filename=file.filename, user_id=current_user["id"])
            finally:
                direct_temp_path.unlink(missing_ok=True)
                # Cleanup staging PDF
                from app.garage_client import delete_garage_object
                delete_garage_object(garage_key)
    except Exception as exc:
        log.exception("Ingest failed, request_id=%s, document_id=%s", request_id, document_id)
        # Cleanup staging PDF on failure
        try:
            from app.garage_client import delete_garage_object
            delete_garage_object(garage_key)
        except Exception as cleanup_exc:
            log.warning("Failed to cleanup staging PDF, request_id=%s: %s", request_id, cleanup_exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    
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
    request: Request,
    body: QueryRequest,
    current_user: dict = Depends(get_current_user),
) -> QueryResponse:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    resolved_doc_id = _resolved_document_id(body.document_id, current_user["id"])
    user_uuid = UUID(current_user["id"])
    request_id = getattr(request.state, "request_id", "unknown")

    if temporal_client:
        log.info("Using Temporal workflow for query, request_id=%s", request_id)
        from uuid import uuid4
        # Use UUID instead of hash to avoid collisions with concurrent identical questions
        workflow_id = f"query-{uuid4()}"
        result = await temporal_client.execute_workflow(
            QueryWorkflow.run,
            QueryParams(question=body.question, document_id=resolved_doc_id, user_id=str(user_uuid)),
            id=workflow_id,
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
        log.info("Using direct execution for query (Temporal unavailable), request_id=%s", request_id)
        packed = run_rag_pipeline(body.question, resolved_doc_id, user_uuid)

    # Save query to history
    try:
        db.save_query_history(
            user_id=user_uuid,
            question=body.question,
            answer=packed.get("answer"),
            document_id=UUID(resolved_doc_id) if resolved_doc_id else None,
            sources=packed.get("sources"),
        )
    except Exception as exc:
        log.warning("Failed to save query history: %s", exc)
        # Don't fail the query if history save fails

    return QueryResponse(**packed)


@app.post("/query/stream")
def query_stream(
    request: Request,
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
    user_uuid = UUID(current_user["id"])
    request_id = getattr(request.state, "request_id", "unknown")

    def event_generator():
        try:
            for event in stream_rag_pipeline(body.question, resolved_doc_id, user_uuid):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            log.exception("SSE streaming generation error, request_id=%s", request_id)
            yield f"data: {json.dumps({'event': 'error', 'detail': 'An error occurred', 'request_id': request_id})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )
