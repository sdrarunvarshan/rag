from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from uuid import UUID
from app.cache import ping as valkey_ping
from app.db import fetch_document
from app.langgraph_rag import run_rag_pipeline
from app.retrieve import retrieve


mcp = FastMCP(
    name="Structure-Aware RAG",
)


# ---------------------------------------------------------------------------
# Full RAG query
# ---------------------------------------------------------------------------

@mcp.tool
def query_document(
    question: str,
    document_id: str | None = None,
) -> dict[str, Any]:
    """
    Ask a question about the indexed document corpus.

    The RAG pipeline performs:

    query understanding
        → pgvector + BM25
        → RRF fusion
        → similarity reranking
        → hierarchical expansion
        → table retrieval
        → context organization
        → LangGraph
        → LangChain + Qwen

    Args:
        question: Natural-language question about the indexed documents.
        document_id: Optional document UUID. If supplied, retrieval is
            restricted to that document.

    Returns:
        Complete RAG response including answer, sources, context,
        query plan, structured context, and pipeline flow.
    """

    return run_rag_pipeline(
        question=question,
        document_id=document_id,
    )


# ---------------------------------------------------------------------------
# Retrieval-only query
# ---------------------------------------------------------------------------

@mcp.tool
def retrieve_document_context(
    question: str,
    document_id: str | None = None,
) -> dict[str, Any]:
    """
    Retrieve relevant document information without calling the LLM.

    Useful for inspecting retrieval quality, including:

    - query understanding
    - vector hits
    - BM25 hits
    - RRF fusion
    - reranking
    - hierarchical expansion
    - tables
    - structured context

    Args:
        question: Natural-language search question.
        document_id: Optional document UUID.

    Returns:
        Retrieval result and structured context.
    """

    return retrieve(
        question=question,
        document_id=document_id,
    )


# ---------------------------------------------------------------------------
# Get document metadata
# ---------------------------------------------------------------------------
@mcp.tool
def get_document(
    document_id: str,
) -> dict[str, Any]:
    """
    Get metadata for an indexed document.

    Args:
        document_id: UUID of the indexed document.
    """

    try:
        document_uuid = UUID(document_id)
        document = fetch_document(document_uuid)

        if document is None:
            return {
                "found": False,
                "document_id": document_id,
            }

        return {
            "found": True,
            "document": document,
        }

    except ValueError:
        return {
            "found": False,
            "document_id": document_id,
            "error": "Invalid document UUID",
        }

# ---------------------------------------------------------------------------
# Valkey health
# ---------------------------------------------------------------------------

@mcp.tool
def cache_health() -> dict[str, Any]:
    """
    Check whether the Valkey cache is reachable.

    Returns:
        Valkey connectivity status.
    """

    healthy = valkey_ping()

    return {
        "service": "valkey",
        "healthy": healthy,
        "status": "ok" if healthy else "unavailable",
    }


# ---------------------------------------------------------------------------
# RAG system health
# ---------------------------------------------------------------------------

@mcp.tool
def rag_health() -> dict[str, Any]:
    """
    Check the health of the RAG cache layer.

    PostgreSQL health should be checked through the existing application's
    database health function if one is available.
    """

    valkey_ok = valkey_ping()

    return {
        "service": "structure-aware-rag",
        "valkey": {
            "healthy": valkey_ok,
            "status": "ok" if valkey_ok else "unavailable",
        },
    }


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()