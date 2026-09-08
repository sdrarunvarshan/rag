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

# Stronger system prompt for real generation
SYSTEM_PROMPT = """You are a helpful assistant that answers questions using the provided document context.

Rules:
1. Base your answer ONLY on the retrieved sections. Do not use outside knowledge.
2. Write a clear, natural, complete answer in your own words.
3. Do NOT just copy or quote the retrieved text. Synthesize and explain.
4. If the context contains a definition, explain it properly in a full paragraph.
5. If the context is insufficient to answer, say so clearly and stop.
6. Keep the answer concise but complete (usually 3–8 sentences).
7. When useful, mention the relevant section heading.

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


def generate_answer(question: str, context: str) -> tuple[str, bool]:
    if not LLM_API_KEY:
        return "LLM skipped: set HF_TOKEN in .env", True
    if not context.strip():
        return "No matching sections were retrieved for this question.", False

    user_content = f"""Answer the following question using only the retrieved document sections below.

Question:
{question}

Retrieved sections:
{context}

Write a clear and complete answer in your own words."""

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
        return text, False
    except Exception as exc:
        log.warning("Hugging Face generation failed: %s", exc)
        return f"LLM skipped: {exc}", True
