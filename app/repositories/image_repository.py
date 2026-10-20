from __future__ import annotations

from typing import Any
from uuid import UUID

from app.repositories.session import connect


def insert_image(
    image_id: UUID,
    document_id: UUID,
    node_id: UUID | None,
    minio_key: str,
    page: int | None,
    caption: str | None,
    mime_type: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO images (id, document_id, node_id, minio_key, page, caption, mime_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (image_id, document_id, node_id, minio_key, page, caption, mime_type),
        )
        conn.commit()


def fetch_images_by_document(document_id: UUID, user_id: UUID | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if user_id:
            rows = conn.execute(
                """
                SELECT i.id, i.document_id, i.node_id, i.minio_key, i.page, i.caption, i.mime_type, i.created_at
                FROM images i
                INNER JOIN documents d ON i.document_id = d.id
                WHERE i.document_id = %s AND d.user_id = %s
                ORDER BY i.page, i.created_at
                """,
                (document_id, user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, document_id, node_id, minio_key, page, caption, mime_type, created_at
                FROM images
                WHERE document_id = %s
                ORDER BY page, created_at
                """,
                (document_id,),
            ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "document_id": str(row["document_id"]),
            "node_id": str(row["node_id"]) if row["node_id"] else None,
            "minio_key": row["minio_key"],
            "page": row["page"],
            "caption": row["caption"],
            "mime_type": row["mime_type"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def fetch_images_by_node(node_id: UUID, user_id: UUID | None = None) -> list[dict[str, Any]]:
    """user_id=None is the legacy unscoped path. Tenant retrieval must pass the owner."""
    with connect() as conn:
        if user_id:
            rows = conn.execute(
                """
                SELECT i.id, i.document_id, i.node_id, i.minio_key, i.page, i.caption, i.mime_type, i.created_at
                FROM images i
                INNER JOIN documents d ON i.document_id = d.id
                WHERE i.node_id = %s AND d.user_id = %s
                ORDER BY i.page, i.created_at
                """,
                (node_id, user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, document_id, node_id, minio_key, page, caption, mime_type, created_at
                FROM images
                WHERE node_id = %s
                ORDER BY page, created_at
                """,
                (node_id,),
            ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "document_id": str(row["document_id"]),
            "node_id": str(row["node_id"]) if row["node_id"] else None,
            "minio_key": row["minio_key"],
            "page": row["page"],
            "caption": row["caption"],
            "mime_type": row["mime_type"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def fetch_image(image_id: UUID, user_id: UUID | None = None) -> dict[str, Any] | None:
    with connect() as conn:
        if user_id:
            # Join with documents to enforce ownership check
            row = conn.execute(
                """
                SELECT i.id, i.document_id, i.node_id, i.minio_key, i.page, i.caption, i.mime_type, i.created_at
                FROM images i
                INNER JOIN documents d ON i.document_id = d.id
                WHERE i.id = %s AND d.user_id = %s
                """,
                (image_id, user_id),
            ).fetchone()
        else:
            # WARNING: No ownership check when user_id is None
            # This should only be used in trusted single-user contexts
            row = conn.execute(
                """
                SELECT id, document_id, node_id, minio_key, page, caption, mime_type, created_at
                FROM images
                WHERE id = %s
                """,
                (image_id,),
            ).fetchone()
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "document_id": str(row["document_id"]),
        "node_id": str(row["node_id"]) if row["node_id"] else None,
        "minio_key": row["minio_key"],
        "page": row["page"],
        "caption": row["caption"],
        "mime_type": row["mime_type"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def image_belongs_to_user(image_id: UUID, user_id: UUID) -> bool:
    """Check if an image belongs to a user via its parent document."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM images i
            INNER JOIN documents d ON i.document_id = d.id
            WHERE i.id = %s AND d.user_id = %s
            """,
            (image_id, user_id),
        ).fetchone()
    return row is not None
