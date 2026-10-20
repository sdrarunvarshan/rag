"""Faithfulness, answer relevancy, and contextual relevancy via DeepEval."""

from __future__ import annotations

from deepeval.metrics import AnswerRelevancyMetric, ContextualRelevancyMetric, FaithfulnessMetric


def quality_metrics(
    model: str,
    api_key: str,
    base_url: str,
    threshold: float = 0.7,
) -> list:
    kwargs = {
        "threshold": threshold,
        "model": model,
        "api_key": api_key,
        "custom_model_endpoint": base_url,
    }
    return [
        FaithfulnessMetric(**kwargs),
        AnswerRelevancyMetric(**kwargs),
        ContextualRelevancyMetric(**kwargs),
    ]
