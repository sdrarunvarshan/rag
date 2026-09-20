from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.config import DATABASE_URL, DATABASE_URL_FALLBACK

log = logging.getLogger(__name__)

_active_url: str | None = None


def _auth_failed(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "password authentication failed",
            "authentication failed",
            "28p01",
        )
    )


def _try_connect(url: str, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(
        url,
        row_factory=dict_row,
        connect_timeout=5,
        autocommit=autocommit,
    )


def resolve_database_url() -> str:
    global _active_url
    if _active_url:
        return _active_url
    candidates = [DATABASE_URL]
    if DATABASE_URL_FALLBACK and DATABASE_URL_FALLBACK not in candidates:
        candidates.append(DATABASE_URL_FALLBACK)
    last_error: Exception | None = None
    for url in candidates:
        try:
            with _try_connect(url) as conn:
                conn.execute("SELECT 1")
            _active_url = url
            if url != DATABASE_URL:
                log.warning("Primary DATABASE_URL auth failed; using fallback user")
            return url
        except Exception as exc:
            last_error = exc
            if _auth_failed(exc):
                log.warning("Postgres auth failed for %s", urlparse(url).username)
                continue
            if "does not exist" in str(exc).lower():
                _active_url = url
                return url
            raise
    assert last_error is not None
    raise last_error


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS documents (
        id UUID PRIMARY KEY,
        filename TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nodes (
        id UUID PRIMARY KEY,
        document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        parent_id UUID REFERENCES nodes(id) ON DELETE CASCADE,
        node_type TEXT NOT NULL CHECK (node_type IN ('section', 'subsection', 'table')),
        heading TEXT,
        text TEXT,
        page INTEGER,
        path TEXT,
        search_text TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_nodes_document_id ON nodes(document_id)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_parent_id ON nodes(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type)",
)


def _admin_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path="/postgres"))


def ensure_database() -> None:
    url = resolve_database_url()
    try:
        with _try_connect(url) as conn:
            conn.execute("SELECT 1")
        return
    except psycopg.OperationalError as exc:
        message = str(exc).lower()
        if "does not exist" not in message:
            raise
        log.warning("Database missing; attempting CREATE DATABASE rag")

    admin = _admin_url(url)
    db_name = (urlparse(url).path or "/rag").lstrip("/") or "rag"
    with _try_connect(admin, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{db_name}"')


def init_schema() -> None:
    ensure_database()
    with connect() as conn:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        
        # Add embedding column if it doesn't exist (for existing databases)
        try:
            conn.execute("ALTER TABLE nodes ADD COLUMN IF NOT EXISTS embedding vector(384)")
        except Exception as exc:
            log.warning("Could not add embedding column: %s", exc)
        
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_embedding ON nodes USING ivfflat (embedding vector_cosine_ops)")
        except Exception as exc:
            log.warning("Could not create embedding index: %s", exc)
        
        conn.commit()


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    conn = _try_connect(resolve_database_url())
    try:
        yield conn
    finally:
        conn.close()


def ping() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as exc:
        log.warning("Postgres ping failed: %s", exc)
        return False


def insert_document(doc_id: UUID, filename: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, filename) VALUES (%s, %s)",
            (doc_id, filename),
        )
        conn.commit()


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


def fetch_all_index_rows() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, document_id, search_text
            FROM nodes
            WHERE COALESCE(search_text, '') <> ''
            ORDER BY path NULLS LAST, id
            """
        ).fetchall()
    return list(rows)


def fetch_nodes_by_ids(ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM nodes WHERE id = ANY(%s)",
            (ids,),
        ).fetchall()
    by_id = {row["id"]: row for row in rows}
    return [by_id[i] for i in ids if i in by_id]


def fetch_node(node_id: UUID) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = %s", (node_id,)).fetchone()
    return dict(row) if row else None


def fetch_children(
    parent_id: UUID,
    limit: int = 32,
    node_type: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM nodes WHERE parent_id = %s"
    params: list[Any] = [parent_id]
    if node_type:
        sql += " AND node_type = %s"
        params.append(node_type)
    sql += " ORDER BY path NULLS LAST, id LIMIT %s"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return list(rows)


def fetch_siblings(node: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    node_id = node["id"]
    parent_id = node.get("parent_id")
    with connect() as conn:
        if parent_id:
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


def fetch_tables_under(root_ids: list[UUID], limit: int = 24) -> list[dict[str, Any]]:
    if not root_ids:
        return []
    with connect() as conn:
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


def document_exists(document_id: UUID) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
    return row is not None


def list_documents() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, created_at
            FROM documents
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "filename": row["filename"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def fetch_document(document_id: UUID) -> dict[str, Any] | None:
    with connect() as conn:
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


def vector_search(query_embedding: list[float], limit: int = 20, document_id: UUID | None = None) -> list[dict[str, Any]]:
    sql = """
    SELECT id, document_id, 1 - (embedding <=> %s::vector) as similarity
    FROM nodes
    WHERE embedding IS NOT NULL
    """
    params: list[Any] = [query_embedding]
    
    if document_id:
        sql += " AND document_id = %s"
        params.append(document_id)
    
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
