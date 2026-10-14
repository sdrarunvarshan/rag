from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from uuid import UUID
from app.cache import ping as valkey_ping
from app.db import fetch_document, fetch_images_by_document
from app.garage_client import ping as garage_ping
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

    WARNING: This MCP tool has no user/tenant context and should not be exposed
    as a multi-user service. It's intended for trusted single-user local stdio processes.

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
        user_id=None,  # MCP tools have no user context
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

    WARNING: This MCP tool has no user/tenant context and should not be exposed
    as a multi-user service. It's intended for trusted single-user local stdio processes.

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
        user_id=None,  # MCP tools have no user context
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

    WARNING: This MCP tool has no user/tenant context and should not be exposed
    as a multi-user service. It's intended for trusted single-user local stdio processes.

    Args:
        document_id: UUID of the indexed document.
    """

    try:
        document_uuid = UUID(document_id)
        # MCP tools have no user context - pass None for user_id
        # This returns the document if it exists without ownership check
        # WARNING: Do not expose this endpoint in multi-user deployments
        document = fetch_document(document_uuid, user_id=None)

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
# Get document images
# ---------------------------------------------------------------------------

@mcp.tool
def get_document_images(
    document_id: str,
) -> dict[str, Any]:
    """
    Get all images extracted from a document.

    WARNING: This MCP tool has no user/tenant context and should not be exposed
    as a multi-user service. It's intended for trusted single-user local stdio processes.

    Args:
        document_id: UUID of the indexed document.

    Returns:
        List of images with MinIO references and metadata.
    """

    try:
        document_uuid = UUID(document_id)
        # MCP tools have no user context - pass None for user_id
        # WARNING: Do not expose this endpoint in multi-user deployments
        images = fetch_images_by_document(document_uuid, user_id=None)

        return {
            "document_id": document_id,
            "images": images,
            "count": len(images),
        }

    except ValueError:
        return {
            "document_id": document_id,
            "images": [],
            "count": 0,
            "error": "Invalid document UUID",
        }

# ---------------------------------------------------------------------------
# Valkey health
# ---------------------------------------------------------------------------

@mcp.tool
def cache_health() -> dict[str, Any]:
    """
    Check whether the Valkey cache and Garage are reachable.

    Returns:
        Valkey and Garage connectivity status.
    """

    valkey_healthy = valkey_ping()
    garage_healthy = garage_ping()

    return {
        "service": "cache",
        "valkey": {
            "healthy": valkey_healthy,
            "status": "ok" if valkey_healthy else "unavailable",
        },
        "garage": {
            "healthy": garage_healthy,
            "status": "ok" if garage_healthy else "unavailable",
        },
    }


# ---------------------------------------------------------------------------
# RAG system health
# ---------------------------------------------------------------------------

@mcp.tool
def rag_health() -> dict[str, Any]:
    """
    Check the health of the RAG cache and storage layers.

    PostgreSQL health should be checked through the existing application's
    database health function if one is available.
    """

    valkey_ok = valkey_ping()
    garage_ok = garage_ping()

    return {
        "service": "structure-aware-rag",
        "valkey": {
            "healthy": valkey_ok,
            "status": "ok" if valkey_ok else "unavailable",
        },
        "garage": {
            "healthy": garage_ok,
            "status": "ok" if garage_ok else "unavailable",
        },
    }


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()