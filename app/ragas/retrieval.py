"""Retrieval precision, recall, and F1."""

from __future__ import annotations


def precision(retrieved: set[str], relevant: set[str]) -> float:
    if not retrieved:
        return 0.0
    return len(retrieved & relevant) / len(retrieved)


def recall(retrieved: set[str], relevant: set[str]) -> float:
    if not relevant:
        return 0.0
    return len(retrieved & relevant) / len(relevant)


def f1(retrieved: set[str], relevant: set[str]) -> float:
    precise = precision(retrieved, relevant)
    recalled = recall(retrieved, relevant)
    if precise + recalled == 0:
        return 0.0
    return 2 * precise * recalled / (precise + recalled)


def retrieval_scores(retrieved: set[str], relevant: set[str]) -> dict[str, float]:
    return {
        "precision": precision(retrieved, relevant),
        "recall": recall(retrieved, relevant),
        "f1": f1(retrieved, relevant),
    }
