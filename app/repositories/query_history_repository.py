from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from app.repositories.session import connect


def save_query_history(
    user_id: UUID,
    question: str,
    answer: str | None,
    document_id: UUID | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> UUID:
    """
    Save a query to the history.
    
    Returns the query history ID.
    """
    query_id = uuid4()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO query_history (id, user_id, question, answer, document_id, sources)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (query_id, user_id, question, answer, document_id, json.dumps(sources) if sources else None),
        )
        conn.commit()
    return query_id


def fetch_query_history(user_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
    """
    Fetch query history for a user, most recent first.
    
    Args:
        user_id: The user's ID
        limit: Maximum number of queries to return
        
    Returns:
        List of query history entries
    """
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, question, answer, document_id, sources, created_at
            FROM query_history
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        ).fetchall()
    
    return [
        {
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "question": row["question"],
            "answer": row["answer"],
            "document_id": str(row["document_id"]) if row["document_id"] else None,
            "sources": json.loads(row["sources"]) if row["sources"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def delete_query_history(query_id: UUID, user_id: UUID) -> bool:
    """
    Delete a query from history (only if it belongs to the user).
    
    Returns True if deleted, False if not found or doesn't belong to user.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM query_history WHERE id = %s AND user_id = %s",
                (query_id, user_id),
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted
