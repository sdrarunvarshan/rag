from __future__ import annotations

from typing import Any
from uuid import UUID

from app.repositories.session import connect


def insert_document(doc_id: UUID, user_id: UUID, filename: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, user_id, filename) VALUES (%s, %s, %s)",
            (doc_id, user_id, filename),
        )
        conn.commit()


def document_exists(document_id: UUID, user_id: UUID) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE id = %s AND user_id = %s", (document_id, user_id)
        ).fetchone()
    return row is not None


def list_documents(user_id: UUID) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, created_at
            FROM documents
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,)
        ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "filename": row["filename"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def fetch_document(document_id: UUID, user_id: UUID | None = None) -> dict[str, Any] | None:
    with connect() as conn:
        if user_id:
            row = conn.execute(
                "SELECT id, filename, created_at FROM documents WHERE id = %s AND user_id = %s",
                (document_id, user_id),
            ).fetchone()
        else:
            # WARNING: No ownership check when user_id is None
            # This should only be used in trusted single-user contexts (e.g., MCP tools)
            row = conn.execute(
                "SELECT id, filename, created_at FROM documents WHERE id = %s",
                (document_id,),
            ).fetchone()
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "filename": row["filename"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def delete_document(document_id: UUID, user_id: UUID) -> bool:
    """Delete document from PostgreSQL. Child nodes and images cascade delete."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s AND user_id = %s", (document_id, user_id))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted
