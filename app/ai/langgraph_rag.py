from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.llm import generate_answer, iter_answer_tokens
from app.retrieve import build_query_flow, retrieve


class RAGState(TypedDict, total=False):
    question: str
    document_id: str | None
    user_id: UUID | None
    retrieval: dict[str, Any]
    answer: str
    llm_skipped: bool


def retrieve_node(state: RAGState) -> dict[str, Any]:
    retrieval = retrieve(state["question"], state.get("document_id"), user_id=state.get("user_id"))
    return {"retrieval": retrieval}


def generate_node(state: RAGState) -> dict[str, Any]:
    retrieval = state.get("retrieval") or {}
    answer, skipped = generate_answer(
        state["question"],
        retrieval.get("context") or "",
        retrieval.get("query_plan"),
    )
    return {"answer": answer, "llm_skipped": skipped}


def _compile_graph():
    graph = StateGraph(RAGState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


_GRAPH = _compile_graph()


def sources_from_retrieval(retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for item in retrieval.get("sections") or []:
        sources.append(
            {
                "section_id": item["section_id"],
                "document_id": item["document_id"],
                "heading": item["heading"],
                "node_type": item["node_type"],
                "page": item["page"],
                "path": item["path"],
                "hit_node_id": item["hit_node_id"],
                "hit_node_type": item["hit_node_type"],
                "score": item.get("score"),
                "role": "section",
            }
        )
    for table in retrieval.get("tables") or []:
        sources.append(
            {
                "section_id": table.get("id"),
                "document_id": table.get("document_id"),
                "heading": table.get("heading"),
                "node_type": "table",
                "page": table.get("page"),
                "path": table.get("path"),
                "hit_node_id": table.get("id"),
                "hit_node_type": "table",
                "score": None,
                "role": "table",
            }
        )
    return sources


def attach_graph_stage(flow: dict[str, dict], llm_skipped: bool) -> dict[str, dict]:
    stages = dict(flow)
    stages["graph"] = {
        "key": "graph",
        "title": "LangGraph",
        "summary": "retrieve → generate (hybrid search unchanged)",
        "data": {
            "nodes": ["retrieve", "generate"],
            "hybrid": "pgvector + BM25 + RRF",
            "llm_skipped": llm_skipped,
        },
    }
    return stages


def pack_response(question: str, document_id: str | None, state: RAGState, user_id: UUID | None = None) -> dict[str, Any]:
    retrieval = state.get("retrieval") or {}
    answer = state.get("answer") or ""
    llm_skipped = bool(state.get("llm_skipped"))
    images = retrieval.get("images") or []
    flow = build_query_flow(question, document_id, retrieval, answer, llm_skipped, user_id)
    flow = attach_graph_stage(flow, llm_skipped)
    return {
        "answer": answer,
        "cached": bool(retrieval.get("cached")),
        "sources": sources_from_retrieval(retrieval),
        "images": images,
        "context": retrieval.get("context") or "",
        "flow": flow,
        "llm_skipped": llm_skipped,
        "query_plan": retrieval.get("query_plan") or {},
        "structured": retrieval.get("structured") or [],
    }


def run_rag_pipeline(question: str, document_id: str | None = None, user_id: UUID | None = None) -> dict[str, Any]:
    state = _GRAPH.invoke({"question": question, "document_id": document_id, "user_id": user_id})
    return pack_response(question, document_id, state, user_id)


def stream_rag_pipeline(question: str, document_id: str | None = None, user_id: UUID | None = None):
    """Yield SSE-friendly dicts: retrieved → token* → done."""
    retrieval = retrieve(question, document_id, user_id=user_id)
    yield {
        "event": "retrieved",
        "cached": bool(retrieval.get("cached")),
        "query_plan": retrieval.get("query_plan") or {},
        "sources": sources_from_retrieval(retrieval),
        "images": retrieval.get("images") or [],
        "structured": retrieval.get("structured") or [],
        "context": retrieval.get("context") or "",
    }
    parts: list[str] = []
    skipped = False
    for piece in iter_answer_tokens(
        question,
        retrieval.get("context") or "",
        retrieval.get("query_plan"),
    ):
        if piece.startswith("LLM skipped:"):
            skipped = True
        parts.append(piece)
        yield {"event": "token", "text": piece}
    answer = "".join(parts)
    packed = pack_response(
        question,
        document_id,
        {
            "question": question,
            "document_id": document_id,
            "user_id": user_id,
            "retrieval": retrieval,
            "answer": answer,
            "llm_skipped": skipped,
        },
        user_id,
    )
    yield {"event": "done", **packed}
