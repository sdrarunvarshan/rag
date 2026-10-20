"""Compatibility import. The LangGraph pipeline lives in app.ai."""

from app.ai.langgraph_rag import run_rag_pipeline, stream_rag_pipeline

__all__ = ["run_rag_pipeline", "stream_rag_pipeline"]
