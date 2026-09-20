from __future__ import annotations

import logging
import re
from collections.abc import Iterator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

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

SYSTEM_PROMPT = """You are a grounded document QA assistant.

Use only the structured retrieved context. Never use outside knowledge.

How to write:
- Reply with the user-facing answer only.
- Do not write labels such as Thinking Process, Analysis, Scan, Extract, Synthesize, Draft, or Final Review.
- Do not list numbered reasoning steps.
- Write 3–8 clear sentences in your own words.
- Cite facts as [Heading (p. N)]. If a number or list comes from a Table block, name that table.
- If the context is insufficient, say so in one or two sentences and stop.

Never invent facts."""

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
_REASONING_HEAD = re.compile(
    r"(?is)^\s*(thinking process|analysis|let me think|chain of thought)\s*:?\s*"
)


def chat_model() -> ChatOpenAI:
    """Qwen via Hugging Face OpenAI-compatible router (HF_TOKEN as api_key)."""
    return ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=LLM_API_KEY,
        base_url=OPENAI_BASE_URL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        top_p=LLM_TOP_P,
        presence_penalty=LLM_PRESENCE_PENALTY,
        extra_body={
            "top_k": LLM_TOP_K,
            "enable_thinking": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )


def build_messages(question: str, context: str, query_plan: dict | None = None) -> list:
    plan = query_plan or {}
    plan_line = (
        f"Query type: {plan.get('query_type', 'general')}. "
        f"Scope: {plan.get('scope', 'hierarchical')}."
    )
    user_content = f"""{plan_line}

Question:
{question}

Structured context:
{context}

Start the answer on the next line. Do not include any preamble."""
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]


def public_text(raw: str) -> str:
    """Drop model reasoning so only the grounded answer is shown."""
    text = (raw or "").strip()
    if not text:
        return ""
    text = _THINK_BLOCK.sub("", text).strip()
    text = _THINK_OPEN.sub("", text).strip()
    if _REASONING_HEAD.match(text):
        for marker in ("Final Answer:", "Final answer:", "\nAnswer:\n", "\nAnswer:"):
            if marker in text:
                text = text.split(marker, 1)[-1].strip()
                break
        else:
            draft = re.search(
                r"(?is)(?:^|\n)\s*\*?\s*Draft:\s*(.+?)(?:\n\s*(?:\d+\.|Final Review)|$)",
                text,
            )
            if draft:
                text = draft.group(1).strip()
            else:
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
                keep: list[str] = []
                for para in paragraphs:
                    lowered = para.lower()
                    if lowered.startswith("thinking") or re.match(r"^\d+\.\s", para):
                        continue
                    if para.startswith(("- ", "* ")):
                        continue
                    keep.append(para)
                text = "\n\n".join(keep).strip() if keep else ""
    return text.strip()


def _message_text(message) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    reasoning = getattr(message, "additional_kwargs", {}) or {}
    for key in ("reasoning_content", "reasoning"):
        value = reasoning.get(key)
        if isinstance(value, str) and value.strip():
            log.info("Model returned reasoning field %s; stripping from user answer", key)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return content or ""


def generate_answer(
    question: str,
    context: str,
    query_plan: dict | None = None,
) -> tuple[str, bool]:
    if not LLM_API_KEY:
        return "LLM skipped: set HF_TOKEN in .env", True
    if not context.strip():
        return "No matching sections were retrieved for this question.", False

    try:
        message = chat_model().invoke(build_messages(question, context, query_plan))
        text = public_text(_message_text(message))
        if not text:
            return (
                "The model returned no user-facing answer. Try the question again.",
                False,
            )
        return text, False
    except Exception as exc:
        log.warning("Hugging Face generation failed: %s", exc)
        return f"LLM skipped: {exc}", True


def iter_answer_tokens(
    question: str,
    context: str,
    query_plan: dict | None = None,
) -> Iterator[str]:
    if not LLM_API_KEY:
        yield "LLM skipped: set HF_TOKEN in .env"
        return
    if not context.strip():
        yield "No matching sections were retrieved for this question."
        return

    buffer = ""
    emitted = 0
    try:
        for chunk in chat_model().stream(build_messages(question, context, query_plan)):
            buffer += _message_text(chunk)
            visible = public_text(buffer) if "</think>" in buffer.lower() or "<think>" not in buffer.lower() else ""
            if "<think>" in buffer.lower() and "</think>" not in buffer.lower():
                continue
            if len(visible) > emitted:
                yield visible[emitted:]
                emitted = len(visible)
        visible = public_text(buffer)
        if len(visible) > emitted:
            yield visible[emitted:]
    except Exception as exc:
        log.warning("Hugging Face streaming failed: %s", exc)
        yield f"LLM skipped: {exc}"
