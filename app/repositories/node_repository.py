from __future__ import annotations

from typing import Any
from uuid import UUID

from app.repositories.session import connect


def insert_nodes(document_id: UUID, nodes: list[dict[str, Any]]) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            for node in nodes:
                cur.execute(
                    """
                    INSERT INTO nodes (
                        id, document_id, parent_id, node_type, heading,
                        text, page, path, search_text, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                    """,
                    (
                        node["id"],
                        document_id,
                        node["parent_id"],
                        node["node_type"],
                        node["heading"],
                        node["text"],
                        node["page"],
                        node["path"],
                        node["search_text"],
                    ),
                )
        conn.commit()


def fetch_all_index_rows(user_id: UUID | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if user_id:
            rows = conn.execute(
                """
                SELECT n.id, n.document_id, d.user_id, n.search_text
                FROM nodes n
                INNER JOIN documents d ON n.document_id = d.id
                WHERE COALESCE(n.search_text, '') <> '' AND d.user_id = %s
                ORDER BY n.path NULLS LAST, n.id
                """,
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT n.id, n.document_id, d.user_id, n.search_text
                FROM nodes n
                INNER JOIN documents d ON n.document_id = d.id
                WHERE COALESCE(n.search_text, '') <> ''
                ORDER BY n.path NULLS LAST, n.id
                """
            ).fetchall()
    return list(rows)


def fetch_nodes_by_ids(ids: list[UUID], user_id: UUID | None = None) -> list[dict[str, Any]]:
    if not ids:
        return []
    with connect() as conn:
        if user_id:
            rows = conn.execute(
                """
                SELECT n.*
                FROM nodes n
                INNER JOIN documents d ON n.document_id = d.id
                WHERE n.id = ANY(%s) AND d.user_id = %s
                """,
                (ids, user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE id = ANY(%s)",
                (ids,),
            ).fetchall()
    by_id = {row["id"]: row for row in rows}
    return [by_id[i] for i in ids if i in by_id]


def fetch_node(node_id: UUID, user_id: UUID | None = None) -> dict[str, Any] | None:
    """Load a node. user_id=None is the legacy unscoped path and must not be used for tenant requests."""
    with connect() as conn:
        if user_id:
            row = conn.execute(
                """
                SELECT n.*
                FROM nodes n
                INNER JOIN documents d ON n.document_id = d.id
                WHERE n.id = %s AND d.user_id = %s
                """,
                (node_id, user_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM nodes WHERE id = %s", (node_id,)).fetchone()
    return dict(row) if row else None


def fetch_children(
    parent_id: UUID,
    limit: int = 32,
    node_type: str | None = None,
    user_id: UUID | None = None,
) -> list[dict[str, Any]]:
    if user_id:
        sql = """
            SELECT n.*
            FROM nodes n
            INNER JOIN documents d ON n.document_id = d.id
            WHERE n.parent_id = %s AND d.user_id = %s
        """
        params: list[Any] = [parent_id, user_id]
    else:
        sql = "SELECT * FROM nodes WHERE parent_id = %s"
        params = [parent_id]
    if node_type:
        sql += " AND node_type = %s" if not user_id else " AND n.node_type = %s"
        params.append(node_type)
    sql += " ORDER BY path NULLS LAST, id LIMIT %s" if not user_id else " ORDER BY n.path NULLS LAST, n.id LIMIT %s"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return list(rows)


def fetch_siblings(node: dict[str, Any], limit: int = 8, user_id: UUID | None = None) -> list[dict[str, Any]]:
    node_id = node["id"]
    parent_id = node.get("parent_id")
    with connect() as conn:
        if user_id and parent_id:
            rows = conn.execute(
                """
                SELECT n.*
                FROM nodes n
                INNER JOIN documents d ON n.document_id = d.id
                WHERE n.parent_id = %s AND n.id <> %s AND d.user_id = %s
                ORDER BY n.path NULLS LAST, n.id
                LIMIT %s
                """,
                (parent_id, node_id, user_id, limit),
            ).fetchall()
        elif user_id:
            rows = conn.execute(
                """
                SELECT n.*
                FROM nodes n
                INNER JOIN documents d ON n.document_id = d.id
                WHERE n.parent_id IS NULL AND n.document_id = %s AND n.id <> %s AND d.user_id = %s
                ORDER BY n.path NULLS LAST, n.id
                LIMIT %s
                """,
                (node["document_id"], node_id, user_id, limit),
            ).fetchall()
        elif parent_id:
            rows = conn.execute(
                """
                SELECT * FROM nodes
                WHERE parent_id = %s AND id <> %s
                ORDER BY path NULLS LAST, id
                LIMIT %s
                """,
                (parent_id, node_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM nodes
                WHERE parent_id IS NULL AND document_id = %s AND id <> %s
                ORDER BY path NULLS LAST, id
                LIMIT %s
                """,
                (node["document_id"], node_id, limit),
            ).fetchall()
    return list(rows)


def fetch_tables_under(root_ids: list[UUID], limit: int = 24, user_id: UUID | None = None) -> list[dict[str, Any]]:
    if not root_ids:
        return []
    with connect() as conn:
        if user_id:
            rows = conn.execute(
                """
                WITH RECURSIVE tree AS (
                    SELECT n.id, n.document_id, n.parent_id, n.node_type, n.heading, n.text, n.page, n.path, n.search_text
                    FROM nodes n
                    INNER JOIN documents d ON n.document_id = d.id
                    WHERE n.id = ANY(%s) AND d.user_id = %s
                    UNION
                    SELECT c.id, c.document_id, c.parent_id, c.node_type, c.heading, c.text, c.page, c.path, c.search_text
                    FROM nodes c
                    INNER JOIN tree t ON c.parent_id = t.id AND c.document_id = t.document_id
                )
                SELECT id, document_id, parent_id, node_type, heading, text, page, path, search_text
                FROM tree
                WHERE node_type = 'table'
                ORDER BY path NULLS LAST, id
                LIMIT %s
                """,
                (root_ids, user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                WITH RECURSIVE tree AS (
                    SELECT id, document_id, parent_id, node_type, heading, text, page, path, search_text
                    FROM nodes WHERE id = ANY(%s)
                    UNION
                    SELECT n.id, n.document_id, n.parent_id, n.node_type, n.heading, n.text, n.page, n.path, n.search_text
                    FROM nodes n
                    INNER JOIN tree t ON n.parent_id = t.id
                )
                SELECT id, document_id, parent_id, node_type, heading, text, page, path, search_text
                FROM tree
                WHERE node_type = 'table'
                ORDER BY path NULLS LAST, id
                LIMIT %s
                """,
                (root_ids, limit),
            ).fetchall()
    return list(rows)


def fetch_subtree(root_id: UUID) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            WITH RECURSIVE tree AS (
                SELECT id, document_id, parent_id, node_type, heading, text, page, path, search_text
                FROM nodes WHERE id = %s
                UNION ALL
                SELECT n.id, n.document_id, n.parent_id, n.node_type, n.heading, n.text, n.page, n.path, n.search_text
                FROM nodes n
                INNER JOIN tree t ON n.parent_id = t.id
            )
            SELECT id, document_id, parent_id, node_type, heading, text, page, path, search_text
            FROM tree
            ORDER BY path NULLS LAST, id
            """,
            (root_id,),
        ).fetchall()
    return list(rows)


def node_counts(document_id: UUID | None = None) -> dict[str, int]:
    sql = "SELECT node_type, COUNT(*) AS n FROM nodes"
    params: tuple[Any, ...] = ()
    if document_id is not None:
        sql += " WHERE document_id = %s"
        params = (document_id,)
    sql += " GROUP BY node_type"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    counts = {"section": 0, "subsection": 0, "table": 0}
    for row in rows:
        counts[str(row["node_type"])] = int(row["n"])
    counts["total"] = sum(counts.values())
    return counts


def tree_preview(document_id: UUID, limit: int = 80) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT path, node_type, heading, page
            FROM nodes
            WHERE document_id = %s
            ORDER BY path NULLS LAST, id
            LIMIT %s
            """,
            (document_id, limit),
        ).fetchall()
    return [
        {
            "path": row["path"],
            "node_type": row["node_type"],
            "heading": row["heading"],
            "page": row["page"],
        }
        for row in rows
    ]


def summarize_nodes(ids: list[str]) -> list[dict[str, Any]]:
    uuids: list[UUID] = []
    for raw in ids:
        try:
            uuids.append(UUID(str(raw)))
        except ValueError:
            continue
    rows = fetch_nodes_by_ids(uuids)
    return [
        {
            "id": str(row["id"]),
            "heading": row.get("heading"),
            "node_type": row["node_type"],
            "path": row.get("path"),
            "page": row.get("page"),
        }
        for row in rows
    ]


def upsert_embedding(node_id: UUID, embedding: list[float]) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE nodes SET embedding = %s WHERE id = %s",
            (embedding, node_id),
        )
        conn.commit()


def upsert_embeddings_batch(embeddings_data: list[tuple[UUID, list[float]]]) -> None:
    if not embeddings_data:
        return
    with connect() as conn:
        with conn.cursor() as cur:
            for node_id, embedding in embeddings_data:
                cur.execute(
                    "UPDATE nodes SET embedding = %s WHERE id = %s",
                    (embedding, node_id),
                )
        conn.commit()


def vector_search(query_embedding: list[float], limit: int = 20, document_id: UUID | None = None, user_id: UUID | None = None) -> list[dict[str, Any]]:
    if user_id and document_id:
        # Both user_id and document_id provided - filter by both
        sql = """
        SELECT n.id, n.document_id, 1 - (n.embedding <=> %s::vector) as similarity
        FROM nodes n
        INNER JOIN documents d ON n.document_id = d.id
        WHERE n.embedding IS NOT NULL AND n.document_id = %s AND d.user_id = %s
        """
        params: list[Any] = [query_embedding, document_id, user_id]
    elif user_id:
        # Only user_id provided - filter by user (all documents owned by user)
        sql = """
        SELECT n.id, n.document_id, 1 - (n.embedding <=> %s::vector) as similarity
        FROM nodes n
        INNER JOIN documents d ON n.document_id = d.id
        WHERE n.embedding IS NOT NULL AND d.user_id = %s
        """
        params = [query_embedding, user_id]
    elif document_id:
        # Only document_id provided - filter by document (no user check)
        sql = """
        SELECT id, document_id, 1 - (embedding <=> %s::vector) as similarity
        FROM nodes
        WHERE embedding IS NOT NULL AND document_id = %s
        """
        params = [query_embedding, document_id]
    else:
        # No filtering - search all nodes (WARNING: not tenant-isolated)
        sql = """
        SELECT id, document_id, 1 - (embedding <=> %s::vector) as similarity
        FROM nodes
        WHERE embedding IS NOT NULL
        """
        params = [query_embedding]
    
    sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
    params.extend([query_embedding, limit])
    
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    
    return [
        {
            "id": str(row["id"]),
            "document_id": str(row["document_id"]),
            "score": float(row["similarity"]),
        }
        for row in rows
    ]
