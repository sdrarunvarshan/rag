from __future__ import annotations

import os
from typing import Any, Callable
from functools import wraps

from fastmcp import FastMCP
from uuid import UUID
from app.cache import ping as valkey_ping
from app.db import fetch_document, fetch_images_by_document
from app.garage_client import ping as garage_ping
from app.langgraph_rag import run_rag_pipeline
from app.retrieve import retrieve


def create_rag_mcp_server(user_id: UUID | str | None = None) -> FastMCP:
    """
    Create an MCP server with user_id injected from authenticated session.
    
    This implements the closure pattern: user_id is captured from the
    authenticated session context and injected into all tool calls.
    The LLM never sees user_id as a parameter - it's server-side only.
    
    Args:
        user_id: The authenticated user's ID from the session/JWT.
                If None, checks MCP_USER_ID environment variable.
                If still None, uses legacy single-user mode.
        
    Returns:
        Configured FastMCP server with user_id-injected tools
    """
    
    # Check environment variable if user_id not provided
    if user_id is None:
        env_user_id = os.environ.get("MCP_USER_ID")
        if env_user_id:
            user_id = UUID(env_user_id)
    
    # Convert to UUID if string
    if isinstance(user_id, str):
        user_id = UUID(user_id)
    
    # If still no user_id, use legacy single-user mode
    if user_id is None:
        print("WARNING: No user_id provided - using legacy single-user mode")
        return create_legacy_mcp_server()
    
    mcp = FastMCP(
        name="Structure-Aware RAG",
    )
    
    # Helper to inject user_id into tool calls
    def with_user_id(func: Callable) -> Callable:
        """Decorator to inject user_id into tool calls."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Ensure user_id is set (server-side enforcement)
            kwargs['user_id'] = user_id
            return func(*args, **kwargs)
        return wrapper
    
    # ---------------------------------------------------------------------------
    # Full RAG query
    # ---------------------------------------------------------------------------
    
    @mcp.tool
    @with_user_id
    def query_document(
        question: str,
        document_id: str | None = None,
        user_id: UUID = None,  # Injected server-side, not LLM-facing
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
            user_id=user_id,
        )
    
    
    # ---------------------------------------------------------------------------
    # Retrieval-only query
    # ---------------------------------------------------------------------------
    
    @mcp.tool
    @with_user_id
    def retrieve_document_context(
        question: str,
        document_id: str | None = None,
        user_id: UUID = None,  # Injected server-side, not LLM-facing
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
            user_id=user_id,
        )
    
    
    # ---------------------------------------------------------------------------
    # Get document metadata
    # ---------------------------------------------------------------------------
    @mcp.tool
    @with_user_id
    def get_document(
        document_id: str,
        user_id: UUID = None,  # Injected server-side, not LLM-facing
    ) -> dict[str, Any]:
        """
        Get metadata for an indexed document.
        
        Args:
            document_id: UUID of the indexed document.
        """
        
        try:
            document_uuid = UUID(document_id)
            document = fetch_document(document_uuid, user_id)
        
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
    @with_user_id
    def get_document_images(
        document_id: str,
        user_id: UUID = None,  # Injected server-side, not LLM-facing
    ) -> dict[str, Any]:
        """
        Get all images extracted from a document.
        
        Args:
            document_id: UUID of the indexed document.
        
        Returns:
            List of images with MinIO references and metadata.
        """
        
        try:
            document_uuid = UUID(document_id)
            images = fetch_images_by_document(document_uuid, user_id)
        
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
    # Valkey health (no user_id needed)
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
    # RAG system health (no user_id needed)
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
    
    return mcp


def create_legacy_mcp_server() -> FastMCP:
    """
    Create legacy single-user MCP server.
    
    WARNING: This is for trusted single-user local stdio processes only.
    DO NOT expose this as a multi-user service.
    """
    
    mcp = FastMCP(
        name="Structure-Aware RAG (Legacy - Single User Only)",
    )
    
    @mcp.tool
    def query_document_legacy(
        question: str,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Ask a question about the indexed document corpus.
        
        WARNING: This is a legacy single-user MCP server with no user/tenant context.
        DO NOT expose this as a multi-user service.
        """
        
        return run_rag_pipeline(
            question=question,
            document_id=document_id,
            user_id=None,  # No user context - single user only
        )
    
    @mcp.tool
    def retrieve_document_context_legacy(
        question: str,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve context (legacy single-user mode)."""
        return retrieve(
            question=question,
            document_id=document_id,
            user_id=None,
        )
    
    @mcp.tool
    def get_document_legacy(
        document_id: str,
    ) -> dict[str, Any]:
        """Get document (legacy single-user mode)."""
        try:
            document_uuid = UUID(document_id)
            document = fetch_document(document_uuid, user_id=None)
            if document is None:
                return {"found": False, "document_id": document_id}
            return {"found": True, "document": document}
        except ValueError:
            return {"found": False, "document_id": document_id, "error": "Invalid document UUID"}
    
    @mcp.tool
    def get_document_images_legacy(
        document_id: str,
    ) -> dict[str, Any]:
        """Get document images (legacy single-user mode)."""
        try:
            document_uuid = UUID(document_id)
            images = fetch_images_by_document(document_uuid, user_id=None)
            return {"document_id": document_id, "images": images, "count": len(images)}
        except ValueError:
            return {"document_id": document_id, "images": [], "count": 0, "error": "Invalid document UUID"}
    
    @mcp.tool
    def cache_health_legacy() -> dict[str, Any]:
        """Check cache health (legacy single-user version)."""
        valkey_healthy = valkey_ping()
        garage_healthy = garage_ping()
        return {
            "service": "cache",
            "valkey": {"healthy": valkey_healthy, "status": "ok" if valkey_healthy else "unavailable"},
            "garage": {"healthy": garage_healthy, "status": "ok" if garage_healthy else "unavailable"},
        }
    
    @mcp.tool
    def rag_health_legacy() -> dict[str, Any]:
        """Check RAG health (legacy single-user version)."""
        valkey_ok = valkey_ping()
        garage_ok = garage_ping()
        return {
            "service": "structure-aware-rag",
            "valkey": {"healthy": valkey_ok, "status": "ok" if valkey_ok else "unavailable"},
            "garage": {"healthy": garage_ok, "status": "ok" if garage_ok else "unavailable"},
        }
    
    return mcp


# ---------------------------------------------------------------------------
# Legacy single-user MCP server (for local stdio use only)
# WARNING: Do not use this in multi-user deployments
# ---------------------------------------------------------------------------

mcp = create_legacy_mcp_server()


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Check for MCP_USER_ID environment variable
    env_user_id = os.environ.get("MCP_USER_ID")
    if env_user_id:
        print(f"Multi-user mode with user_id from env: {env_user_id}")
        mcp = create_rag_mcp_server(UUID(env_user_id))
    else:
        print("Legacy single-user mode (no MCP_USER_ID env var)")
        mcp = create_legacy_mcp_server()
    
    mcp.run()
