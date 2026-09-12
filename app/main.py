from __future__ import annotations

import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import cache, db
from app.config import UPLOAD_DIR, ensure_data_dirs
from app.index import hybrid_index
from app.ingest import ingest_pdf
from app.llm import generate_answer
from app.retrieve import build_query_flow, retrieve

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

UI_PAGE = Path(__file__).resolve().parent / "templates" / "index.html"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_data_dirs()
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
        db.ping()
        hybrid_index.load_or_rebuild()
    except Exception as exc:
        log.warning("Index load skipped: %s", exc)
    yield


app = FastAPI(title="Chunkless Structured RAG", lifespan=lifespan)


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
    status = "ok" if postgres and valkey else "degraded"
    return {"status": status, "postgres": postgres, "valkey": valkey}


@app.get("/documents")
def documents() -> dict:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    items = db.list_documents()
    return {"documents": items}


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
        result = ingest_pdf(temp_path, filename=file.filename)
    except Exception as exc:
        log.exception("Ingest failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return result


@app.post("/query", response_model=QueryResponse)
def query(body: QueryRequest) -> QueryResponse:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    document_id = body.document_id
    if document_id:
        try:
            doc_uuid = UUID(document_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="document_id must be a UUID") from exc
        if not db.document_exists(doc_uuid):
            raise HTTPException(status_code=404, detail="document_id not found")
    result = retrieve(body.question, document_id)
    answer, llm_skipped = generate_answer(
        body.question,
        result["context"],
        result.get("query_plan"),
    )
    sources = [
        {
            "section_id": item["section_id"],
            "document_id": item["document_id"],
            "heading": item["heading"],
            "node_type": item["node_type"],
            "page": item["page"],
            "path": item["path"],
            "hit_node_id": item["hit_node_id"],
            "hit_node_type": item["hit_node_type"],
            "score": item.get("score"),
            "role": "section",
        }
        for item in result["sections"]
    ]
    for table in result.get("tables") or []:
        sources.append(
            {
                "section_id": table.get("id"),
                "document_id": table.get("document_id"),
                "heading": table.get("heading"),
                "node_type": "table",
                "page": table.get("page"),
                "path": table.get("path"),
                "hit_node_id": table.get("id"),
                "hit_node_type": "table",
                "score": None,
                "role": "table",
            }
        )
    flow = build_query_flow(body.question, document_id, result, answer, llm_skipped)
    return QueryResponse(
        answer=answer,
        cached=bool(result.get("cached")),
        sources=sources,
        context=result["context"],
        flow=flow,
        llm_skipped=llm_skipped,
        query_plan=result.get("query_plan") or {},
        structured=result.get("structured") or [],
    )
