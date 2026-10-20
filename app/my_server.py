"""Compatibility entry. The MCP server lives in app.ai.my_server."""

from app.ai.my_server import create_legacy_mcp_server, create_rag_mcp_server

__all__ = ["create_legacy_mcp_server", "create_rag_mcp_server"]


if __name__ == "__main__":
    import runpy

    runpy.run_module("app.ai.my_server", run_name="__main__")
