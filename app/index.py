"""Compatibility import. The BM25 index lives in app.bm25."""

from app.bm25.index import HybridIndex, hybrid_index, tokenize

__all__ = ["HybridIndex", "hybrid_index", "tokenize"]
