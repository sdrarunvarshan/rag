from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from temporalio import activity

from app.repositories import insert_document, insert_image, insert_nodes, node_counts, tree_preview
from app.garage_client import ensure_bucket, upload_image, delete_document_images, get_image_bytes
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
    """Parse PDF using Docling from durable Garage storage and return parsed nodes and images."""
    garage_key: str = params["garage_key"]
    filename: str = params["filename"]
    document_id: str = params["document_id"]
    log.info(f"Activity: Parsing PDF from Garage: {garage_key}")
    
    try:
        ensure_bucket()
    except Exception as exc:
        log.warning("Garage bucket unavailable: %s", exc)
        raise
    
    # Download PDF from Garage
    try:
        pdf_bytes, _ = get_image_bytes(garage_key)
    except Exception as exc:
        log.error(f"Failed to download PDF from Garage: {exc}")
        raise
    
    # Write to temporary file for Docling
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_file.write(pdf_bytes)
        temp_path = Path(temp_file.name)
    
    try:
        parsed, images = parse_pdf(temp_path)
    finally:
        # Clean up temp file
        temp_path.unlink(missing_ok=True)
    
    # Store images in Garage and collect keys. A failed upload rolls back keys from this attempt.
    image_keys = []
    image_metadata = []
    doc_uuid = UUID(document_id)

    try:
        for img in images:
            image_id = img.id or uuid4()
            minio_key = upload_image(doc_uuid, img.image_data, img.mime_type, image_id)
            image_keys.append(minio_key)
            image_metadata.append({
                "id": str(image_id),
                "mime_type": img.mime_type,
                "page": img.page,
                "caption": img.caption,
                "node_id": str(img.node_id) if img.node_id else None,
            })
    except Exception:
        from app.garage_client import delete_garage_object

        for key in image_keys:
            try:
                delete_garage_object(key)
            except Exception as cleanup_exc:
                log.warning("Failed to roll back image %s after parse failure: %s", key, cleanup_exc)
        raise
    
    nodes_data = [node.as_row() for node in parsed]
    return {
        "nodes": nodes_data,
        "nodes_count": len(parsed),
        "image_keys": image_keys,
        "image_metadata": image_metadata,
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
    """Insert parsed images into PostgreSQL using pre-uploaded Garage keys."""
    document_id: str = params["document_id"]
    image_keys: list[str] = params["image_keys"]
    image_metadata: list[dict[str, Any]] = params["image_metadata"]
    log.info(f"Activity: Inserting {len(image_keys)} images for document {document_id}")
    doc_uuid = UUID(document_id)
    
    for minio_key, meta in zip(image_keys, image_metadata):
        image_id = UUID(meta["id"])
        node_id = UUID(meta["node_id"]) if meta.get("node_id") else None
        insert_image(
            image_id=image_id,
            document_id=doc_uuid,
            node_id=node_id,
            minio_key=minio_key,
            page=meta["page"],
            caption=meta["caption"],
            mime_type=meta["mime_type"],
        )


@activity.defn
async def rebuild_index_activity() -> None:
    """Rebuild pgvector and BM25 indexes."""
    log.info("Activity: Rebuilding hybrid index")
    hybrid_index.rebuild()


def failed_ingest_cleanup_keys(staging_key: str | None, image_keys: list[str] | None) -> list[str]:
    """Staging PDF plus extracted images from an ingest that did not finish.

    Successfully stored images are not included unless the caller passes them
    because the document itself is being rolled back.
    """
    keys: list[str] = []
    if staging_key:
        keys.append(staging_key)
    for key in image_keys or []:
        if key and key not in keys:
            keys.append(key)
    return keys


@activity.defn
async def delete_partial_document_activity(params: dict[str, Any]) -> None:
    """Remove a document row created by an ingest that did not finish. Safe to retry."""
    from app.repositories import delete_document

    document_id = UUID(params["document_id"])
    user_id = UUID(params["user_id"])
    delete_document(document_id, user_id)


@activity.defn
async def cleanup_garage_activity(params: dict[str, Any]) -> None:
    """Cleanup Garage objects (staging PDFs or failed ingest artifacts)."""
    document_id: str = params["document_id"]
    garage_keys: list[str] = params["garage_keys"]
    log.info(f"Activity: Cleaning up {len(garage_keys)} Garage objects for document {document_id}")
    
    for key in garage_keys:
        try:
            from app.garage_client import delete_garage_object
            delete_garage_object(key)
            log.info(f"Deleted Garage object: {key}")
        except Exception as exc:
            log.warning(f"Failed to delete Garage object {key}: {exc}")
            # Continue cleanup even if one fails


@activity.defn
async def get_ingest_stats_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Get document statistics and tree preview."""
    document_id: str = params["document_id"]
    filename: str = params["filename"]
    nodes_parsed: int = params["nodes_parsed"]
    images_stored: int = params.get("images_stored", 0)
    user_id_str: str | None = params.get("user_id")
    user_id = UUID(user_id_str) if user_id_str else None
    log.info(f"Activity: Getting stats for document {document_id}")
    doc_uuid = UUID(document_id)
    counts = node_counts(doc_uuid, user_id)
    preview = tree_preview(doc_uuid, user_id=user_id)
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
    user_id_str: str | None = params.get("user_id")
    user_id = UUID(user_id_str) if user_id_str else None
    log.info(f"Activity: Retrieving for question: {question[:50]}...")
    retrieval = retrieve(question, document_id, user_id=user_id)
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
