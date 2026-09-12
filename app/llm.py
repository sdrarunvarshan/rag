from __future__ import annotations

import logging
from openai import OpenAI

from app.config import (
    LLM_API_KEY,
    LLM_MAX_TOKENS,
    LLM_PRESENCE_PENALTY,
    LLM_TEMPERATURE,
    LLM_TOP_K,
    LLM_TOP_P,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful assistant that answers questions using structured retrieved context.

The context is labeled:
- Parent section: containing heading and its own prose
- Related section: sibling headings
- Subsection / Matched node: children of the hit
- Table: markdown tables

Rules:
1. Base your answer ONLY on the retrieved blocks. Do not use outside knowledge.
2. Write a clear, natural, complete answer in your own words.
3. Cite the section heading and page when you use a fact.
4. If a number, rate, or list comes from a Table block, name that table.
5. Prefer parent/child prose for explanations; use tables for figures.
6. If the context is insufficient, say so clearly and stop.
7. Keep the answer concise but complete (usually 3–8 sentences).

Never invent facts that are not supported by the context."""


def _client() -> OpenAI:
    return OpenAI(base_url=OPENAI_BASE_URL, api_key=LLM_API_KEY)


def _chat(messages: list[dict], extra_body: dict | None = None):
    body = {"top_k": LLM_TOP_K, **(extra_body or {})}
    return _client().chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
        top_p=LLM_TOP_P,
        presence_penalty=LLM_PRESENCE_PENALTY,
        extra_body=body,
    )


def generate_answer(
    question: str,
    context: str,
    query_plan: dict | None = None,
) -> tuple[str, bool]:
    if not LLM_API_KEY:
        return "LLM skipped: set HF_TOKEN in .env", True
    if not context.strip():
        return "No matching sections were retrieved for this question.", False

    plan = query_plan or {}
    plan_line = (
        f"Query type: {plan.get('query_type', 'general')}. "
        f"Scope: {plan.get('scope', 'hierarchical')}."
    )
    user_content = f"""Answer the following question using only the structured context below.
{plan_line}

Question:
{question}

Structured context:
{context}

Write a grounded answer. Cite headings/pages (and tables when numbers come from them)."""

    try:
        response = _chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        message = response.choices[0].message
        text = (message.content or "").strip()
        if not text:
            text = (getattr(message, "reasoning", None) or "").strip()
        if not text:
            text = (
                "I could not generate a clear answer from the retrieved sections. "
                "The available context does not appear to contain a definition or explanation "
                "for this question."
            )
        return text, False
    except Exception as exc:
        log.warning("Hugging Face generation failed: %s", exc)
        return f"LLM skipped: {exc}", True
