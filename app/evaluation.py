"""Compatibility import. RAGAS evaluation lives in app.ragas."""

from app.ragas.evaluation import RAGASEvaluator, create_sample_evaluation

__all__ = ["RAGASEvaluator", "create_sample_evaluation"]
