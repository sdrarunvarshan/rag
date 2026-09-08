from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from app.cache import get_json, set_json
from app.config import (
    OPENAI_MODEL,
    RERANK_CANDIDATES,
    RRF_K,
    TOP_K_BM25,
    TOP_K_VECTOR,
    TOP_SECTIONS,
)
from app.db import (
    fetch_document,
    fetch_node,
    fetch_subtree,
    node_counts,
    summarize_nodes,
    tree_preview,
)
from app.index import hybrid_index

log = logging.getLogger(__name__)


def _cache_key(question: str, document_id: str | None) -> str:
    payload = json.dumps({"q": question, "d": document_id}, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"rag:flow:v2:{digest}"


def reciprocal_rank_fusion(rank_lists: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranks in rank_lists:
        for rank, node_id in enumerate(ranks, start=1):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def _walk_to_section(node: dict[str, Any]) -> dict[str, Any]:
    current = node
    seen: set[UUID] = set()
    while current.get("parent_id") and current.get("node_type") != "section":
        node_id = current["id"]
        if node_id in seen:
            break
        seen.add(node_id)
        parent = fetch_node(current["parent_id"])
        if parent is None:
            break
        current = parent
    return current


def _format_tree(nodes: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for node in nodes:
        heading = node.get("heading") or node["node_type"].title()
        page = node.get("page")
        page_note = f" (p. {page})" if page else ""
        kind = node["node_type"]
        title = f"### {heading}{page_note}" if kind == "section" else f"#### {heading}{page_note}"
        if kind == "table":
            title = f"#### Table: {heading}{page_note}"
        body = (node.get("text") or "").strip()
        blocks.append(title if not body else f"{title}\n{body}")
    return "\n\n".join(blocks).strip()
    
def build_context(sections: list[dict[str, Any]]) -> str:
    """Clean, LLM-friendly context formatting."""
    if not sections:
        return ""

    parts: list[str] = ["Here are the most relevant sections from the documents:\n"]

    for i, item in enumerate(sections, 1):
        heading = item.get("heading") or "Untitled Section"
        page_info = f", page {item['page']}" if item.get("page") else ""
        path_info = f" [{item['path']}]" if item.get("path") else ""

        parts.append(f"=== Source {i}: {heading}{page_info}{path_info} ===")
        parts.append((item.get("text") or "").strip())
        parts.append("")  # blank line between sources

    return "\n".join(parts).strip()

def expand_section(node_id: UUID) -> dict[str, Any] | None:
    node = fetch_node(node_id)
    if node is None:
        return None
    root = _walk_to_section(node)
    tree = fetch_subtree(root["id"])
    return {
        "section_id": str(root["id"]),
        "document_id": str(root["document_id"]),
        "heading": root.get("heading") or "Section",
        "node_type": root["node_type"],
        "page": root.get("page"),
        "path": root.get("path"),
        "hit_node_id": str(node["id"]),
        "hit_node_type": node["node_type"],
        "text": _format_tree(tree),
    }


def _clip(text: str, limit: int = 4000) -> dict[str, Any]:
    raw = text or ""
    if len(raw) <= limit:
        return {"text": raw, "truncated": False, "chars": len(raw)}
    return {"text": raw[:limit] + "\n…", "truncated": True, "chars": len(raw)}


def retrieve(question: str, document_id: str | None = None, use_cache: bool = True) -> dict[str, Any]:
    key = _cache_key(question, document_id)
    if use_cache:
        cached = get_json(key)
        if cached and "fused" in cached:
            cached["cached"] = True
            return cached

    vector_ids = hybrid_index.vector_search(question, TOP_K_VECTOR, document_id)
    bm25_ids = hybrid_index.bm25_search(question, TOP_K_BM25, document_id)
    fused = reciprocal_rank_fusion([vector_ids, bm25_ids])
    candidate_ids = [node_id for node_id, _score in fused[:RERANK_CANDIDATES]]

    texts: list[str] = []
    for node_id in candidate_ids:
        text = hybrid_index.text_for(node_id)
        if not text:
            row = fetch_node(UUID(node_id))
            text = (row or {}).get("search_text") or ""
        texts.append(text)
    sim_scores = hybrid_index.similarity(question, texts)
    reranked = sorted(
        zip(candidate_ids, sim_scores),
        key=lambda item: item[1],
        reverse=True,
    )

    sections: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    for node_id, score in reranked:
        expanded = expand_section(UUID(node_id))
        if not expanded or not expanded["text"]:
            continue
        section_id = expanded["section_id"]
        if section_id in seen_sections:
            continue
        seen_sections.add(section_id)
        expanded["score"] = float(score)
        sections.append(expanded)
        if len(sections) >= TOP_SECTIONS:
            break

        context = build_context(sections)
    payload = {
        "cached": False,
        "context": context,
        "sections": sections,
        "vector_hits": vector_ids,
        "bm25_hits": bm25_ids,
        "fused": [{"id": node_id, "rrf": score} for node_id, score in fused[:30]],
        "reranked": [{"id": node_id, "score": float(score)} for node_id, score in reranked],
    }
    set_json(key, {k: v for k, v in payload.items() if k != "cached"})
    return payload


def build_query_flow(
    question: str,
    document_id: str | None,
    result: dict[str, Any],
    answer: str,
    llm_skipped: bool,
) -> dict[str, dict[str, Any]]:
    doc_meta = None
    counts = node_counts(UUID(document_id) if document_id else None)
    preview: list[dict[str, Any]] = []
    if document_id:
        doc_meta = fetch_document(UUID(document_id))
        preview = tree_preview(UUID(document_id), limit=40)
    tree_lines = [
        f"{item.get('path') or '-'} [{item['node_type']}] {item.get('heading') or ''}"
        for item in preview
    ]
    vector_rows = summarize_nodes(result.get("vector_hits") or [])
    bm25_rows = summarize_nodes(result.get("bm25_hits") or [])
    fused_meta = {row["id"]: row for row in vector_rows + bm25_rows}
    fused_rows = []
    for item in result.get("fused") or []:
        meta = fused_meta.get(item["id"], {"id": item["id"]})
        fused_rows.append({**meta, "rrf": item.get("rrf")})
    rerank_rows = []
    for item in result.get("reranked") or []:
        meta = fused_meta.get(item["id"])
        if not meta:
            found = summarize_nodes([item["id"]])
            meta = found[0] if found else {"id": item["id"]}
        rerank_rows.append({**meta, "score": item.get("score")})
    section_payload = [
        {
            "heading": item["heading"],
            "path": item.get("path"),
            "page": item.get("page"),
            "hit_node_type": item.get("hit_node_type"),
            **_clip(item.get("text") or "", 3500),
        }
        for item in result.get("sections") or []
    ]
    context_clip = _clip(result.get("context") or "", 5000)
    doc_label = (doc_meta or {}).get("filename") if doc_meta else "All indexed documents"
    stages = [
        {
            "key": "documents",
            "title": "Documents",
            "summary": doc_label or "Indexed corpus",
            "data": {"question": question, "document": doc_meta, "document_id": document_id},
        },
        {
            "key": "docling",
            "title": "Docling",
            "summary": "Using Docling tree stored at ingest (not re-chunked).",
            "data": {"nodes": counts.get("total", 0)},
        },
        {
            "key": "tree",
            "title": "Structured Document Tree",
            "summary": f"{counts.get('total', 0)} heading/table nodes in index",
            "data": {"preview": tree_lines, "total": counts.get("total", 0)},
        },
        {
            "key": "structure",
            "title": "Sections / Subsections / Tables",
            "summary": (
                f"{counts.get('section', 0)} sections · "
                f"{counts.get('subsection', 0)} subsections · "
                f"{counts.get('table', 0)} tables"
            ),
            "data": counts,
        },
        {
            "key": "txtai",
            "title": "txtai Embeddings + Vector Search",
            "summary": f"{len(vector_rows)} vector hits (USearch)",
            "data": {"hits": vector_rows[:12]},
        },
        {
            "key": "bm25",
            "title": "BM25 Search",
            "summary": f"{len(bm25_rows)} lexical hits",
            "data": {"hits": bm25_rows[:12]},
        },
        {
            "key": "hybrid",
            "title": "Hybrid Retrieval",
            "summary": f"RRF fused {len(fused_rows)} ids (k={RRF_K})",
            "data": {"fused": fused_rows[:15]},
        },
        {
            "key": "rerank",
            "title": "Reranking",
            "summary": f"Similarity rerank of {len(rerank_rows)} candidates",
            "data": {"ranked": rerank_rows[:12]},
        },
        {
            "key": "section",
            "title": "Retrieve Full Section",
            "summary": f"Expanded {len(section_payload)} parent sections (with child tables)",
            "data": {"sections": section_payload},
        },
        {
            "key": "context",
            "title": "Context Building",
            "summary": f"{context_clip['chars']} characters assembled for the LLM",
            "data": context_clip,
        },
        {
            "key": "llm",
            "title": "LLM",
            "summary": (answer[:180] if llm_skipped else f"Generated with {OPENAI_MODEL}"),
            "data": {"answer": answer, "skipped": llm_skipped},
        },
    ]
    return {stage["key"]: stage for stage in stages}
