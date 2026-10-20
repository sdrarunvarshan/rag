from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import uuid4

from temporalio import workflow

from app.temporal_activities import (
    cleanup_garage_activity,
    delete_partial_document_activity,
    failed_ingest_cleanup_keys,
    generate_answer_activity,
    get_ingest_stats_activity,
    insert_document_activity,
    insert_images_activity,
    insert_nodes_activity,
    parse_pdf_activity,
    rebuild_index_activity,
    retrieve_activity,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter dataclasses (Temporal execute_activity takes at most 1 argument)
# ---------------------------------------------------------------------------

@dataclass
class ParsePdfParams:
    garage_key: str  # Durable object storage key instead of local path
    filename: str
    document_id: str  # Stable ID for idempotency


@dataclass
class InsertDocumentParams:
    document_id: str
    user_id: str
    filename: str


@dataclass
class InsertNodesParams:
    document_id: str
    nodes: list[dict[str, Any]]


@dataclass
class InsertImagesParams:
    document_id: str
    image_keys: list[str]  # List of Garage object keys instead of hex-encoded bytes
    image_metadata: list[dict[str, Any]]  # Metadata separate from binary data


@dataclass
class GetIngestStatsParams:
    document_id: str
    filename: str
    nodes_parsed: int
    images_stored: int = 0
    user_id: str | None = None


@dataclass
class RetrieveParams:
    question: str
    document_id: str | None = None
    user_id: str | None = None


@dataclass
class GenerateAnswerParams:
    question: str
    context: str
    query_plan: dict[str, Any] | None = None


@dataclass
class CleanupIngestParams:
    document_id: str
    garage_keys: list[str]  # Keys to clean up on failure


@dataclass
class DeletePartialDocumentParams:
    document_id: str
    user_id: str


# ---------------------------------------------------------------------------
# Workflow input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class IngestParams:
    garage_key: str  # Durable object storage key
    filename: str
    user_id: str
    document_id: str  # Stable ID for idempotency


@dataclass
class QueryParams:
    question: str
    document_id: str | None = None
    user_id: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sources_from_retrieval(retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract sources from retrieval result."""
    sources: list[dict[str, Any]] = []
    for item in retrieval.get("sections") or []:
        sources.append(
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
        )
    for table in retrieval.get("tables") or []:
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
    return sources


def attach_graph_stage(flow: dict[str, dict], llm_skipped: bool) -> dict[str, dict]:
    """Attach LangGraph stage to flow."""
    stages = dict(flow)
    stages["graph"] = {
        "key": "graph",
        "title": "LangGraph",
        "summary": "retrieve → generate (hybrid search unchanged)",
        "data": {
            "nodes": ["retrieve", "generate"],
            "hybrid": "pgvector + BM25 + RRF",
            "llm_skipped": llm_skipped,
        },
    }
    return stages


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

@workflow.defn
class IngestWorkflow:
    """Workflow for ingesting PDF documents with durable execution."""

    @workflow.run
    async def run(self, params: IngestParams) -> dict[str, Any]:
        document_id = params.document_id  # Use stable ID from input
        parsed_data: dict[str, Any] | None = None
        document_inserted = False

        try:
            # Step 1: Parse PDF from durable storage
            parsed_data = await workflow.execute_activity(
                parse_pdf_activity,
                ParsePdfParams(
                    garage_key=params.garage_key,
                    filename=params.filename,
                    document_id=document_id,
                ),
                start_to_close_timeout=timedelta(seconds=300),  # 5 minutes for parsing
            )

            # Step 2: Insert document metadata (idempotent)
            await workflow.execute_activity(
                insert_document_activity,
                InsertDocumentParams(
                    document_id=document_id,
                    user_id=params.user_id,
                    filename=params.filename,
                ),
                start_to_close_timeout=timedelta(seconds=30),
            )
            document_inserted = True

            # Step 3: Insert parsed nodes (idempotent)
            await workflow.execute_activity(
                insert_nodes_activity,
                InsertNodesParams(document_id=document_id, nodes=parsed_data["nodes"]),
                start_to_close_timeout=timedelta(seconds=60),
            )

            # Step 4: Insert parsed images (if any) - using object keys instead of bytes
            if parsed_data.get("image_keys"):
                await workflow.execute_activity(
                    insert_images_activity,
                    InsertImagesParams(
                        document_id=document_id,
                        image_keys=parsed_data["image_keys"],
                        image_metadata=parsed_data["image_metadata"],
                    ),
                    start_to_close_timeout=timedelta(seconds=120),
                )

            # Step 5: Rebuild indexes
            await workflow.execute_activity(
                rebuild_index_activity,
                start_to_close_timeout=timedelta(seconds=120),
            )

            # Step 6: Get statistics
            stats = await workflow.execute_activity(
                get_ingest_stats_activity,
                GetIngestStatsParams(
                    document_id=document_id,
                    filename=params.filename,
                    nodes_parsed=parsed_data["nodes_count"],
                    images_stored=parsed_data.get("images_count", 0),
                    user_id=params.user_id,
                ),
                start_to_close_timeout=timedelta(seconds=30),
            )

            # Step 7: Cleanup: delete original PDF from Garage staging
            await workflow.execute_activity(
                cleanup_garage_activity,
                CleanupIngestParams(
                    document_id=document_id,
                    garage_keys=[params.garage_key],
                ),
                start_to_close_timeout=timedelta(seconds=30),
            )

            return stats

        except Exception as exc:
            # Roll back staging PDF and extracted images. A finished document is not cleaned up here.
            # If this process dies before the activity returns uploaded keys, or a delete fails,
            # leftover objects stay for the admin reconcile_garage report. That report does not delete them.
            log.error("Ingest workflow failed for document %s: %s", document_id, exc)
            image_keys = (parsed_data or {}).get("image_keys") or []
            try:
                await workflow.execute_activity(
                    cleanup_garage_activity,
                    CleanupIngestParams(
                        document_id=document_id,
                        garage_keys=failed_ingest_cleanup_keys(params.garage_key, image_keys),
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                )
            except Exception as cleanup_exc:
                log.warning("Garage compensation failed for document %s: %s", document_id, cleanup_exc)
            if document_inserted:
                try:
                    await workflow.execute_activity(
                        delete_partial_document_activity,
                        DeletePartialDocumentParams(
                            document_id=document_id,
                            user_id=params.user_id,
                        ),
                        start_to_close_timeout=timedelta(seconds=30),
                    )
                except Exception as cleanup_exc:
                    log.warning("Partial document cleanup failed for %s: %s", document_id, cleanup_exc)
            raise


@workflow.defn
class QueryWorkflow:
    """Workflow for querying documents with durable execution."""

    @workflow.run
    async def run(self, params: QueryParams) -> dict[str, Any]:
        # Step 1: Retrieve context with user_id for tenant isolation
        retrieval = await workflow.execute_activity(
            retrieve_activity,
            RetrieveParams(
                question=params.question,
                document_id=params.document_id,
                user_id=params.user_id,  # Pass user_id for tenant isolation
            ),
            start_to_close_timeout=timedelta(seconds=60),
        )

        # Step 2: Generate answer
        generation = await workflow.execute_activity(
            generate_answer_activity,
            GenerateAnswerParams(
                question=params.question,
                context=retrieval.get("context", ""),
                query_plan=retrieval.get("query_plan"),
            ),
            start_to_close_timeout=timedelta(seconds=120),
        )

        # Build complete flow with graph stage
        flow = retrieval.get("flow", {})
        flow = attach_graph_stage(flow, generation["llm_skipped"])

        # Combine results
        return {
            "answer": generation["answer"],
            "llm_skipped": generation["llm_skipped"],
            "cached": retrieval.get("cached", False),
            "sources": sources_from_retrieval(retrieval),
            "images": retrieval.get("images", []),
            "context": retrieval.get("context", ""),
            "flow": flow,
            "query_plan": retrieval.get("query_plan", {}),
            "structured": retrieval.get("structured", []),
        }
