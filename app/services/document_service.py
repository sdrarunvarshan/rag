from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException

from app import cache, db
from app.garage_client import (
    delete_document_images,
    get_image_bytes,
    get_image_url,
)
from app.index import hybrid_index

log = logging.getLogger(__name__)


def require_database() -> None:
    if not db.ping():
        raise HTTPException(status_code=503, detail="Postgres is not reachable")


def parse_user_uuid(current_user: dict) -> UUID:
    return UUID(current_user["id"])


def list_user_documents(current_user: dict) -> dict:
    require_database()
    items = db.list_documents(parse_user_uuid(current_user))
    return {"documents": items}


def list_user_query_history(current_user: dict, limit: int = 50) -> dict:
    require_database()
    history = db.fetch_query_history(parse_user_uuid(current_user), limit=limit)
    return {"history": history}


def remove_query_history(query_id: str, current_user: dict) -> dict:
    require_database()
    try:
        query_uuid = UUID(query_id)
        user_uuid = parse_user_uuid(current_user)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query ID")
    deleted = db.delete_query_history(query_uuid, user_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Query not found or access denied")
    return {"deleted": True}


def document_images(document_id: str, current_user: dict) -> dict:
    require_database()
    try:
        doc_uuid = UUID(document_id)
        user_uuid = parse_user_uuid(current_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="document_id must be a UUID") from exc
    if not db.document_exists(doc_uuid, user_uuid):
        raise HTTPException(status_code=404, detail="document_id not found or access denied")
    images = db.fetch_images_by_document(doc_uuid, user_uuid)
    return {"document_id": document_id, "images": images}


def load_image(image_id: str, current_user: dict) -> tuple[bytes, str] | str:
    """Return image bytes and mime type, or a redirect URL string."""
    require_database()
    try:
        img_uuid = UUID(image_id)
        user_uuid = parse_user_uuid(current_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="image_id must be a UUID") from exc
    image_meta = db.fetch_image(img_uuid, user_uuid)
    if not image_meta:
        raise HTTPException(status_code=404, detail="Image not found or access denied")
    try:
        data, mime_type = get_image_bytes(image_meta["minio_key"])
        return data, mime_type or image_meta.get("mime_type") or "image/png"
    except Exception as exc:
        log.warning("Could not read image bytes from Garage: %s", exc)
        try:
            return get_image_url(image_meta["minio_key"])
        except Exception:
            raise HTTPException(status_code=502, detail=f"Image storage unavailable: {exc}")


def delete_document_endpoint(document_id: str, current_user: dict) -> dict:
    """
    Delete a document completely:
    1. Removes all associated images from Garage S3 object store.
    2. Deletes the document row from PostgreSQL (cascades to nodes, images, embeddings).
    3. Rebuilds the hybrid index (BM25 + pgvector).
    4. Invalidates cached retrieval results for the user.

    Returns partial-failure status if Garage deletion fails.
    """
    require_database()
    try:
        doc_uuid = UUID(document_id)
        user_uuid = parse_user_uuid(current_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="document_id must be a UUID") from exc
    if not db.document_exists(doc_uuid, user_uuid):
        raise HTTPException(status_code=404, detail="document_id not found or access denied")

    garage_deleted = False
    db_deleted = False
    index_rebuilt = False
    cache_invalidated = False
    errors = []

    try:
        delete_document_images(doc_uuid)
        garage_deleted = True
        log.info("Deleted images from Garage for document %s", doc_uuid)
    except Exception as exc:
        log.error("Failed to delete images from Garage: %s", exc)
        errors.append(f"Garage deletion failed: {str(exc)}")

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

    if db_deleted:
        try:
            hybrid_index.rebuild_bm25()
            index_rebuilt = True
            log.info("BM25 index updated after deleting document %s", doc_uuid)
        except Exception as exc:
            log.warning("Failed to refresh hybrid index: %s", exc)
            errors.append(f"Index rebuild failed: {str(exc)}")

    if db_deleted:
        try:
            cache.invalidate_user_cache(str(user_uuid))
            cache_invalidated = True
            log.info("Invalidated cache for user %s after deleting document %s", user_uuid, doc_uuid)
        except Exception as exc:
            log.warning("Failed to invalidate user cache: %s", exc)
            errors.append(f"Cache invalidation failed: {str(exc)}")

    if not db_deleted:
        raise HTTPException(
            status_code=500,
            detail=f"Critical failure: {errors[0] if errors else 'Unknown error'}",
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
