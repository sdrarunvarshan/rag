"""Compatibility entry. The agent lives in app.ai.agent."""

from app.ai.agent import ask, create_mcp_client_with_user

__all__ = ["ask", "create_mcp_client_with_user"]


if __name__ == "__main__":
    import runpy

    runpy.run_module("app.ai.agent", run_name="__main__")
