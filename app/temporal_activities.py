from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from temporalio import activity

from app.db import insert_document, insert_nodes, node_counts, tree_preview
from app.ingest import ingest_flow, parse_pdf
from app.index import hybrid_index
from app.llm import generate_answer
from app.retrieve import build_query_flow, retrieve

log = logging.getLogger(__name__)


@activity.defn
async def parse_pdf_activity(pdf_path: str, filename: str) -> dict[str, Any]:
    """Parse PDF using Docling and return parsed nodes."""
    log.info(f"Activity: Parsing PDF {pdf_path}")
    path = Path(pdf_path)
    parsed = parse_pdf(path)
    nodes_data = [node.as_row() for node in parsed]
    return {
        "nodes": nodes_data,
        "nodes_count": len(parsed),
    }


@activity.defn
async def insert_document_activity(document_id: str, filename: str) -> None:
    """Insert document metadata into PostgreSQL."""
    log.info(f"Activity: Inserting document {document_id}")
    doc_uuid = UUID(document_id)
    insert_document(doc_uuid, filename)


@activity.defn
async def insert_nodes_activity(document_id: str, nodes: list[dict[str, Any]]) -> None:
    """Insert parsed nodes into PostgreSQL."""
    log.info(f"Activity: Inserting {len(nodes)} nodes for document {document_id}")
    doc_uuid = UUID(document_id)
    insert_nodes(doc_uuid, nodes)


@activity.defn
async def rebuild_index_activity() -> None:
    """Rebuild pgvector and BM25 indexes."""
    log.info("Activity: Rebuilding hybrid index")
    hybrid_index.rebuild()


@activity.defn
async def get_ingest_stats_activity(
    document_id: str, filename: str, nodes_parsed: int
) -> dict[str, Any]:
    """Get document statistics and tree preview."""
    log.info(f"Activity: Getting stats for document {document_id}")
    doc_uuid = UUID(document_id)
    counts = node_counts(doc_uuid)
    preview = tree_preview(doc_uuid)
    flow = ingest_flow(filename, counts, preview, nodes_parsed)
    return {
        "document_id": document_id,
        "filename": filename,
        "counts": counts,
        "tree_preview": preview,
        "nodes_parsed": nodes_parsed,
        "flow": flow,
    }


@activity.defn
async def retrieve_activity(
    question: str, document_id: str | None
) -> dict[str, Any]:
    """Perform retrieval (hybrid search, RRF, rerank, hierarchy, tables, context)."""
    log.info(f"Activity: Retrieving for question: {question[:50]}...")
    retrieval = retrieve(question, document_id)
    return retrieval


@activity.defn
async def generate_answer_activity(
    question: str, context: str, query_plan: dict[str, Any] | None
) -> dict[str, Any]:
    """Generate answer using LLM from retrieved context."""
    log.info(f"Activity: Generating answer for question: {question[:50]}...")
    answer, skipped = generate_answer(question, context, query_plan)
    return {
        "answer": answer,
        "llm_skipped": skipped,
    }
