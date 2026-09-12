from __future__ import annotations

import re
from typing import Any

from app.index import tokenize

STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "in",
    "on",
    "for",
    "to",
    "from",
    "with",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "what",
    "which",
    "who",
    "whom",
    "where",
    "when",
    "why",
    "how",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "please",
    "tell",
    "me",
    "about",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "compare",
    "comparison",
    "versus",
    "vs",
    "difference",
    "differ",
    "similar",
    "define",
    "definition",
    "meaning",
    "explain",
    "table",
    "figure",
    "many",
    "much",
    "steps",
    "step",
    "procedure",
    "process",
}

DEFINITION_RE = re.compile(
    r"\b(what\s+is|what's|whats|define|definition|meaning\s+of|explain)\b",
    re.I,
)
COMPARISON_RE = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference|differ|similar(?:ity)?)\b",
    re.I,
)
NUMERIC_RE = re.compile(
    r"\b(how\s+many|how\s+much|table|figure|rate|ratio|percent|percentage|"
    r"amount|total|listed|value|number\s+of)\b|%",
    re.I,
)
PROCEDURE_RE = re.compile(
    r"\b(how\s+to|steps?|procedure|process|workflow|instructions?)\b",
    re.I,
)
DOCUMENT_SCOPE_RE = re.compile(
    r"\b(entire\s+document|whole\s+document|overall|all\s+sections|summarize)\b",
    re.I,
)
LOOKUP_RE = re.compile(r"\b(which|where|who|when|list)\b", re.I)


def understand_query(question: str) -> dict[str, Any]:
    text = (question or "").strip()
    query_type = "general"
    if DEFINITION_RE.search(text):
        query_type = "definition"
    elif COMPARISON_RE.search(text):
        query_type = "comparison"
    elif PROCEDURE_RE.search(text):
        query_type = "procedure"
    elif NUMERIC_RE.search(text):
        query_type = "numeric"
    elif LOOKUP_RE.search(text):
        query_type = "lookup"

    if DOCUMENT_SCOPE_RE.search(text):
        scope = "document"
    elif query_type in {"comparison", "procedure", "numeric", "general"}:
        scope = "hierarchical"
    else:
        scope = "local"

    concepts = [token for token in tokenize(text) if token not in STOPWORDS]
    seen: set[str] = set()
    unique: list[str] = []
    for token in concepts:
        if token in seen:
            continue
        seen.add(token)
        unique.append(token)

    include_parent = True
    include_siblings = query_type in {"comparison", "general"} or scope == "document"
    include_children = query_type in {"procedure", "general", "lookup", "definition"}
    prefer_tables = query_type == "numeric"

    lexical = text
    if prefer_tables and "table" not in text.lower():
        lexical = f"{text} table"

    return {
        "question": text,
        "query_type": query_type,
        "scope": scope,
        "concepts": unique[:12],
        "include_parent": include_parent,
        "include_siblings": include_siblings,
        "include_children": include_children,
        "prefer_tables": prefer_tables,
        "lexical_query": lexical,
    }
