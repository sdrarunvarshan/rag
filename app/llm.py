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

SYSTEM_PROMPT = (
    "You answer questions using only the retrieved document sections. "
    "Preserve structure: refer to headings and tables when relevant. "
    "If the context is insufficient, say so clearly."
)


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

    try:
        response = _chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\n"
                        f"Retrieved sections:\n{context}"
                    ),
                },
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
