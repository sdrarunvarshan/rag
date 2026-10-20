from __future__ import annotations

import json
import logging
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import TEMPORAL_TASK_QUEUE
from app.core import runtime
from app.repositories import ping
from app.langgraph_rag import run_rag_pipeline, stream_rag_pipeline
from app.repositories.document_repository import document_exists
from app.repositories.query_history_repository import save_query_history
from app.schemas.query import QueryRequest, QueryResponse
from app.temporal_workflows import QueryParams, QueryWorkflow

log = logging.getLogger(__name__)


def resolved_document_id(document_id: str | None, user_id: str) -> str | None:
    if not document_id:
        return None
    try:
        doc_uuid = UUID(document_id)
        user_uuid = UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="document_id must be a UUID") from exc
    if not document_exists(doc_uuid, user_uuid):
        raise HTTPException(status_code=404, detail="document_id not found or access denied")
    return document_id


async def answer_query(request: Request, body: QueryRequest, current_user: dict) -> QueryResponse:
    if not ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    resolved_doc_id = resolved_document_id(body.document_id, current_user["id"])
    user_uuid = UUID(current_user["id"])
    request_id = getattr(request.state, "request_id", "unknown")

    if runtime.temporal_client:
        log.info("Using Temporal workflow for query, request_id=%s", request_id)
        workflow_id = f"query-{uuid4()}"
        result = await runtime.temporal_client.execute_workflow(
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

    try:
        save_query_history(
            user_id=user_uuid,
            question=body.question,
            answer=packed.get("answer"),
            document_id=UUID(resolved_doc_id) if resolved_doc_id else None,
            sources=packed.get("sources"),
        )
    except Exception as exc:
        log.warning("Failed to save query history: %s", exc)

    return QueryResponse(**packed)


def stream_query(request: Request, body: QueryRequest, current_user: dict) -> StreamingResponse:
    if not ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")
    resolved_doc_id = resolved_document_id(body.document_id, current_user["id"])
    user_uuid = UUID(current_user["id"])
    request_id = getattr(request.state, "request_id", "unknown")

    def event_generator():
        try:
            for event in stream_rag_pipeline(body.question, resolved_doc_id, user_uuid):
                if event.get("event") == "done":
                    try:
                        save_query_history(
                            user_id=user_uuid,
                            question=body.question,
                            answer=event.get("answer"),
                            document_id=UUID(resolved_doc_id) if resolved_doc_id else None,
                            sources=event.get("sources"),
                        )
                    except Exception as exc:
                        log.warning("Failed to save streamed query history: %s", exc)
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
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
