from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from temporalio import activity

from app.db import insert_document, insert_image, insert_nodes, node_counts, tree_preview
from app.garage_client import ensure_bucket, upload_image
from app.ingest import ingest_flow, parse_pdf
from app.index import hybrid_index
from app.llm import generate_answer
from app.retrieve import build_query_flow, retrieve

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ingest activities
# ---------------------------------------------------------------------------

@activity.defn
async def parse_pdf_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Parse PDF using Docling and return parsed nodes and images."""
    pdf_path: str = params["pdf_path"]
    filename: str = params["filename"]
    log.info(f"Activity: Parsing PDF {pdf_path}")
    path = Path(pdf_path)
    try:
        ensure_bucket()
    except Exception as exc:
        log.warning("Garage bucket unavailable (images may not be stored): %s", exc)
    try:
        parsed, images = parse_pdf(path)
    finally:
        # Clean up the temp file that was kept alive for this activity
        path.unlink(missing_ok=True)
        log.info(f"Activity: Deleted temp file {pdf_path}")
    nodes_data = [node.as_row() for node in parsed]
    images_data = [
        {
            "id": str(img.id),
            "image_data": img.image_data.hex(),
            "mime_type": img.mime_type,
            "page": img.page,
            "caption": img.caption,
            "node_id": str(img.node_id) if img.node_id else None,
        }
        for img in images
    ]
    return {
        "nodes": nodes_data,
        "nodes_count": len(parsed),
        "images": images_data,
        "images_count": len(images),
    }


@activity.defn
async def insert_document_activity(params: dict[str, Any]) -> None:
    """Insert document metadata into PostgreSQL."""
    document_id: str = params["document_id"]
    user_id: str = params["user_id"]
    filename: str = params["filename"]
    log.info(f"Activity: Inserting document {document_id}")
    doc_uuid = UUID(document_id)
    user_uuid = UUID(user_id)
    insert_document(doc_uuid, user_uuid, filename)


@activity.defn
async def insert_nodes_activity(params: dict[str, Any]) -> None:
    """Insert parsed nodes into PostgreSQL."""
    document_id: str = params["document_id"]
    nodes: list[dict[str, Any]] = params["nodes"]
    log.info(f"Activity: Inserting {len(nodes)} nodes for document {document_id}")
    doc_uuid = UUID(document_id)
    insert_nodes(doc_uuid, nodes)


@activity.defn
async def insert_images_activity(params: dict[str, Any]) -> None:
    """Insert parsed images into PostgreSQL and MinIO."""
    document_id: str = params["document_id"]
    images: list[dict[str, Any]] = params["images"]
    log.info(f"Activity: Inserting {len(images)} images for document {document_id}")
    doc_uuid = UUID(document_id)
    for img_data in images:
        image_id = UUID(img_data["id"])
        image_bytes = bytes.fromhex(img_data["image_data"])
        minio_key = upload_image(doc_uuid, image_bytes, img_data["mime_type"], image_id)
        node_id = UUID(img_data["node_id"]) if img_data["node_id"] else None
        insert_image(
            image_id=image_id,
            document_id=doc_uuid,
            node_id=node_id,
            minio_key=minio_key,
            page=img_data["page"],
            caption=img_data["caption"],
            mime_type=img_data["mime_type"],
        )


@activity.defn
async def rebuild_index_activity() -> None:
    """Rebuild pgvector and BM25 indexes."""
    log.info("Activity: Rebuilding hybrid index")
    hybrid_index.rebuild()


@activity.defn
async def get_ingest_stats_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Get document statistics and tree preview."""
    document_id: str = params["document_id"]
    filename: str = params["filename"]
    nodes_parsed: int = params["nodes_parsed"]
    images_stored: int = params.get("images_stored", 0)
    log.info(f"Activity: Getting stats for document {document_id}")
    doc_uuid = UUID(document_id)
    counts = node_counts(doc_uuid)
    preview = tree_preview(doc_uuid)
    flow = ingest_flow(filename, counts, preview, nodes_parsed, images_stored)
    return {
        "document_id": document_id,
        "filename": filename,
        "counts": counts,
        "tree_preview": preview,
        "nodes_parsed": nodes_parsed,
        "images_stored": images_stored,
        "flow": flow,
    }


# ---------------------------------------------------------------------------
# Query activities
# ---------------------------------------------------------------------------

@activity.defn
async def retrieve_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Perform retrieval (hybrid search, RRF, rerank, hierarchy, tables, context)."""
    question: str = params["question"]
    document_id: str | None = params.get("document_id")
    log.info(f"Activity: Retrieving for question: {question[:50]}...")
    retrieval = retrieve(question, document_id)
    return retrieval


@activity.defn
async def generate_answer_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Generate answer using LLM from retrieved context."""
    question: str = params["question"]
    context: str = params["context"]
    query_plan: dict[str, Any] | None = params.get("query_plan")
    log.info(f"Activity: Generating answer for question: {question[:50]}...")
    answer, skipped = generate_answer(question, context, query_plan)
    return {
        "answer": answer,
        "llm_skipped": skipped,
    }
