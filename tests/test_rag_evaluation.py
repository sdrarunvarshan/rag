"""
DeepEval integration tests for RAG system evaluation.

IMPORTANT: These are integration tests that require:
- A live Hugging Face endpoint/token for DeepEval
- External LLM services for evaluation
- These are NOT deterministic unit tests

These tests should be run separately from unit tests as an optional
evaluation job in CI. They require external services and secrets.

Run with: pytest tests/test_rag_evaluation.py -v
"""

import pytest
from deepeval import assert_test

pytestmark = pytest.mark.evaluation
from deepeval.metrics import (
    FaithfulnessMetric,
    AnswerRelevancyMetric,
    ContextualRelevancyMetric,
)
from deepeval.test_case import LLMTestCase

from app.config import get_settings


@pytest.fixture
def evaluation_config():
    """Fixture for evaluation configuration."""
    settings = get_settings()
    return {
        "model": settings.openai_model,
        "api_key": settings.llm_api_key,
        "base_url": settings.openai_base_url,
    }


def test_faithfulness(evaluation_config):
    """
    Test that answers are faithful to the retrieved context.
    Ensures the model doesn't hallucinate information not in context.
    """
    test_case = LLMTestCase(
        input="What is structure-aware chunking?",
        actual_output="Structure-aware chunking uses Docling to parse PDFs into heading/table trees and indexes at section, subsection, and table granularity without fixed-size token chunking.",
        retrieval_context=[
            "PDF documents are parsed with Docling into a heading / table tree and indexed at section, subsection, and table granularity. There is no fixed-size token chunking.",
        ],
    )
    
    metric = FaithfulnessMetric(
        threshold=0.7,
        model=evaluation_config["model"],
        api_key=evaluation_config["api_key"],
        custom_model_endpoint=evaluation_config["base_url"],
    )
    
    assert_test(test_case, [metric])


def test_answer_relevancy(evaluation_config):
    """
    Test that answers are relevant to the user's question.
    Ensures the model addresses the actual query.
    """
    test_case = LLMTestCase(
        input="How does query understanding work?",
        actual_output="Query understanding classifies query type, scope, and concepts to drive expansion and BM25 query shaping.",
        retrieval_context=[
            "Query Understanding: Classifies query type, scope, concepts; sets expansion flags",
            "Query understanding (type, scope, concepts) drives expansion and BM25 query shaping",
        ],
    )
    
    metric = AnswerRelevancyMetric(
        threshold=0.7,
        model=evaluation_config["model"],
        api_key=evaluation_config["api_key"],
        custom_model_endpoint=evaluation_config["base_url"],
    )
    
    assert_test(test_case, [metric])


def test_contextual_relevancy(evaluation_config):
    """
    Test that retrieved context is relevant to the question.
    Ensures the retrieval system finds appropriate context.
    """
    test_case = LLMTestCase(
        input="What is the retrieval strategy?",
        actual_output="The system uses hybrid search with dense vector search and BM25, fused with RRF.",
        retrieval_context=[
            "Hybrid search: dense (pgvector + sentence-transformers) + lexical (BM25), fused with RRF",
            "RRF Fusion: Reciprocal Rank Fusion merges rank lists",
        ],
    )
    
    metric = ContextualRelevancyMetric(
        threshold=0.7,
        model=evaluation_config["model"],
        api_key=evaluation_config["api_key"],
        custom_model_endpoint=evaluation_config["base_url"],
    )
    
    assert_test(test_case, [metric])


def test_rag_pipeline_quality(evaluation_config):
    """
    Comprehensive test of RAG pipeline quality.
    Tests multiple metrics together.
    """
    test_case = LLMTestCase(
        input="What makes this RAG system unique?",
        actual_output="This RAG system is unique because it uses structure-aware chunking with Docling to parse PDFs into heading/table trees, indexes at section/subsection/table granularity without fixed-size token chunking, and uses hybrid search with pgvector and BM25 fused with RRF.",
        retrieval_context=[
            "Structure-aware ingest (headings and tables, not sliding-window chunks)",
            "Hybrid search: dense (pgvector + sentence-transformers) + lexical (BM25), fused with RRF",
            "Hierarchical expansion: parent section, siblings, children, and dedicated table retrieval",
        ],
    )
    
    metrics = [
        FaithfulnessMetric(
            threshold=0.7,
            model=evaluation_config["model"],
            api_key=evaluation_config["api_key"],
            custom_model_endpoint=evaluation_config["base_url"],
        ),
        AnswerRelevancyMetric(
            threshold=0.7,
            model=evaluation_config["model"],
            api_key=evaluation_config["api_key"],
            custom_model_endpoint=evaluation_config["base_url"],
        ),
        ContextualRelevancyMetric(
            threshold=0.7,
            model=evaluation_config["model"],
            api_key=evaluation_config["api_key"],
            custom_model_endpoint=evaluation_config["base_url"],
        ),
    ]
    
    assert_test(test_case, metrics)


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
