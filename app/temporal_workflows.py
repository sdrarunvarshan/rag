from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from temporalio import workflow

from app.temporal_activities import (
    get_ingest_stats_activity,
    generate_answer_activity,
    insert_document_activity,
    insert_images_activity,
    insert_nodes_activity,
    parse_pdf_activity,
    rebuild_index_activity,
    retrieve_activity,
)

log = logging.getLogger(__name__)


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


@dataclass
class IngestParams:
    pdf_path: str
    filename: str


@dataclass
class QueryParams:
    question: str
    document_id: str | None = None


@workflow.defn
class IngestWorkflow:
    """Workflow for ingesting PDF documents with durable execution."""

    @workflow.run
    async def run(self, params: IngestParams) -> dict[str, Any]:
        document_id = str(uuid4())

        # Step 1: Parse PDF
        parsed_data = await workflow.execute_activity(
            parse_pdf_activity,
            params.pdf_path,
            params.filename,
            start_to_close_timeout=300,  # 5 minutes for parsing
        )

        # Step 2: Insert document metadata
        await workflow.execute_activity(
            insert_document_activity,
            document_id,
            params.filename,
            start_to_close_timeout=30,
        )

        # Step 3: Insert parsed nodes
        await workflow.execute_activity(
            insert_nodes_activity,
            document_id,
            parsed_data["nodes"],
            start_to_close_timeout=60,
        )

        # Step 4: Insert parsed images (if any)
        if parsed_data.get("images"):
            await workflow.execute_activity(
                insert_images_activity,
                document_id,
                parsed_data["images"],
                start_to_close_timeout=120,
            )

        # Step 5: Rebuild indexes
        await workflow.execute_activity(
            rebuild_index_activity,
            start_to_close_timeout=120,
        )

        # Step 6: Get statistics
        stats = await workflow.execute_activity(
            get_ingest_stats_activity,
            document_id,
            params.filename,
            parsed_data["nodes_count"],
            parsed_data.get("images_count", 0),
            start_to_close_timeout=30,
        )

        return stats


@workflow.defn
class QueryWorkflow:
    """Workflow for querying documents with durable execution."""

    @workflow.run
    async def run(self, params: QueryParams) -> dict[str, Any]:
        # Step 1: Retrieve context
        retrieval = await workflow.execute_activity(
            retrieve_activity,
            params.question,
            params.document_id,
            start_to_close_timeout=60,
        )

        # Step 2: Generate answer
        generation = await workflow.execute_activity(
            generate_answer_activity,
            params.question,
            retrieval.get("context", ""),
            retrieval.get("query_plan"),
            start_to_close_timeout=120,
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
