from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from app.cache import get_json, set_json, track_cache_key
from app.config import (
    CONTEXT_CHAR_BUDGET,
    MAX_CHILDREN,
    MAX_SIBLINGS,
    MAX_TABLES,
    OPENAI_MODEL,
    RERANK_CANDIDATES,
    RRF_K,
    TABLE_RERANK_BONUS,
    TOP_K_BM25,
    TOP_K_VECTOR,
    TOP_SECTIONS,
)
from app.repositories import (
    fetch_children,
    fetch_document,
    fetch_images_by_node,
    fetch_node,
    fetch_nodes_by_ids,
    fetch_siblings,
    fetch_tables_under,
    node_counts,
    summarize_nodes,
    tree_preview,
)
from app.index import hybrid_index
from app.query_understand import understand_query

log = logging.getLogger(__name__)


def _cache_key(question: str, document_id: str | None, user_id: UUID | None = None) -> str:
    payload = json.dumps({"q": question, "d": document_id, "u": str(user_id) if user_id else None}, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"rag:flow:v4:{digest}"


def reciprocal_rank_fusion(rank_lists: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranks in rank_lists:
        for rank, node_id in enumerate(ranks, start=1):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def _walk_to_section(node: dict[str, Any], user_id: UUID | None = None) -> dict[str, Any]:
    current = node
    seen: set[UUID] = set()
    while current.get("parent_id") and current.get("node_type") != "section":
        node_id = current["id"]
        if node_id in seen:
            break
        seen.add(node_id)
        parent = fetch_node(current["parent_id"], user_id)
        if parent is None:
            break
        current = parent
    return current


def _brief(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not node:
        return None
    return {
        "id": str(node["id"]),
        "document_id": str(node["document_id"]),
        "heading": node.get("heading") or node["node_type"].title(),
        "node_type": node["node_type"],
        "page": node.get("page"),
        "path": node.get("path"),
        "text": (node.get("text") or "").strip(),
        "parent_id": str(node["parent_id"]) if node.get("parent_id") else None,
    }


def _briefs(nodes: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    items = [_brief(node) for node in nodes]
    cleaned = [item for item in items if item]
    if limit is not None:
        return cleaned[:limit]
    return cleaned


def expand_hit(node_id: UUID, plan: dict[str, Any], user_id: UUID | None = None) -> dict[str, Any] | None:
    node = fetch_node(node_id, user_id)
    if node is None:
        return None
    parent = _walk_to_section(node, user_id)
    siblings = fetch_siblings(node, MAX_SIBLINGS, user_id) if plan.get("include_siblings") else []
    children: list[dict[str, Any]] = []
    if plan.get("include_children") or plan.get("prefer_tables"):
        children = fetch_children(node["id"], MAX_CHILDREN, user_id=user_id)
        if plan.get("prefer_tables"):
            children = [child for child in children if child["node_type"] == "table"]
        elif not plan.get("include_children"):
            children = []
    parent_brief = _brief(parent)
    hit_brief = _brief(node)
    return {
        "section_id": str(parent["id"]),
        "document_id": str(parent["document_id"]),
        "heading": parent.get("heading") or "Section",
        "node_type": parent["node_type"],
        "page": parent.get("page"),
        "path": parent.get("path"),
        "hit_node_id": str(node["id"]),
        "hit_node_type": node["node_type"],
        "parent": parent_brief,
        "hit": hit_brief,
        "siblings": _briefs(siblings, MAX_SIBLINGS),
        "children": _briefs(children, MAX_CHILDREN),
        "text": (parent.get("text") or "").strip(),
    }


def retrieve_tables(
    reranked: list[tuple[str, float]],
    expansions: list[dict[str, Any]],
    plan: dict[str, Any],
    user_id: UUID | None = None,
) -> list[dict[str, Any]]:
    table_ids: list[str] = []
    seen: set[str] = set()

    def add(node: dict[str, Any] | None) -> None:
        if not node or node.get("node_type") != "table":
            return
        node_id = str(node["id"])
        if node_id in seen:
            return
        seen.add(node_id)
        table_ids.append(node_id)

    rerank_uuids: list[UUID] = []
    for node_id, _score in reranked:
        try:
            rerank_uuids.append(UUID(node_id))
        except ValueError:
            continue
    for row in fetch_nodes_by_ids(rerank_uuids, user_id):
        add(row)

    root_ids = [UUID(item["section_id"]) for item in expansions]
    for row in fetch_tables_under(root_ids, MAX_TABLES * 2, user_id):
        add(row)

    tables = _briefs(fetch_nodes_by_ids([UUID(nid) for nid in table_ids], user_id), MAX_TABLES)
    if plan.get("prefer_tables"):
        return tables
    return tables[:MAX_TABLES]


def retrieve_images(
    hit_nodes: list[Any],
    expansions: list[dict[str, Any]],
    user_id: UUID | None = None,
) -> list[dict[str, Any]]:
    node_uuids: list[UUID] = []
    seen_nodes: set[str] = set()

    def add_node(nid: Any) -> None:
        if nid is None:
            return
        if isinstance(nid, (tuple, list)) and nid:
            nid = nid[0]
        if isinstance(nid, dict):
            nid = nid.get("id") or nid.get("hit_node_id") or nid.get("section_id")
        try:
            u = UUID(str(nid))
            if str(u) not in seen_nodes:
                seen_nodes.add(str(u))
                node_uuids.append(u)
        except (ValueError, TypeError):
            pass

    for hit in hit_nodes:
        add_node(hit)

    for item in expansions:
        add_node(item.get("section_id"))
        add_node(item.get("hit_node_id"))
        if item.get("parent"):
            add_node(item["parent"].get("id"))
        if item.get("hit"):
            add_node(item["hit"].get("id"))
        for child in item.get("children") or []:
            add_node(child.get("id"))
        for sibling in item.get("siblings") or []:
            add_node(sibling.get("id"))

    images: list[dict[str, Any]] = []
    seen_image_ids: set[str] = set()
    for node_id in node_uuids:
        for img in fetch_images_by_node(node_id, user_id):
            img_id = str(img["id"])
            if img_id not in seen_image_ids:
                seen_image_ids.add(img_id)
                img_copy = dict(img)
                if not img_copy.get("url"):
                    img_copy["url"] = f"/images/{img_id}"
                images.append(img_copy)

    return images


def _block_text(role: str, node: dict[str, Any]) -> str:
    labels = {
        "parent": "Parent section",
        "sibling": "Related section",
        "child": "Subsection",
        "hit": "Matched node",
        "table": "Table",
    }
    heading = node.get("heading") or role.title()
    page = f" (p. {node['page']})" if node.get("page") else ""
    path = f" [{node['path']}]" if node.get("path") else ""
    title = f"### {labels.get(role, role)}: {heading}{page}{path}"
    body = (node.get("text") or "").strip()
    return title if not body else f"{title}\n{body}"


def organize_context(
    plan: dict[str, Any],
    expansions: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    def push(role: str, node: dict[str, Any] | None, priority: int) -> None:
        if not node:
            return
        node_id = str(node.get("id") or "")
        if not node_id or node_id in used_ids:
            return
        text = (node.get("text") or "").strip()
        if not text and role != "parent":
            return
        used_ids.add(node_id)
        candidates.append({"role": role, "priority": priority, "node": node})

    parent_priority = 1 if plan.get("prefer_tables") else 0
    table_priority = 0 if plan.get("prefer_tables") else 2
    child_priority = 1 if not plan.get("prefer_tables") else 3
    sibling_priority = 4 if plan.get("prefer_tables") else 3

    for item in expansions:
        if plan.get("include_parent"):
            push("parent", item.get("parent"), parent_priority)
        hit = item.get("hit")
        if hit and hit.get("id") != (item.get("parent") or {}).get("id"):
            role = "table" if hit.get("node_type") == "table" else "hit"
            push(role, hit, table_priority if role == "table" else child_priority)
        if plan.get("include_children"):
            for child in item.get("children") or []:
                role = "table" if child.get("node_type") == "table" else "child"
                push(role, child, table_priority if role == "table" else child_priority)
        if plan.get("include_siblings"):
            for sibling in item.get("siblings") or []:
                push("sibling", sibling, sibling_priority)

    for table in tables:
        push("table", table, table_priority)

    candidates.sort(key=lambda item: (item["priority"],))
    selected: list[dict[str, Any]] = []
    parts: list[str] = [
        "[Query]",
        (
            f"type={plan.get('query_type')} scope={plan.get('scope')} "
            f"concepts={', '.join(plan.get('concepts') or []) or '(none)'}"
        ),
        "",
    ]
    used = len("\n".join(parts))
    for item in candidates:
        block = _block_text(item["role"], item["node"])
        extra = len(block) + 2
        if selected and used + extra > CONTEXT_CHAR_BUDGET:
            continue
        selected.append(
            {
                "role": item["role"],
                "id": item["node"].get("id"),
                "heading": item["node"].get("heading"),
                "path": item["node"].get("path"),
                "page": item["node"].get("page"),
                "node_type": item["node"].get("node_type"),
                "chars": len(item["node"].get("text") or ""),
            }
        )
        parts.append(block)
        parts.append("")
        used += extra

    text = "\n".join(parts).strip()
    return {"text": text, "blocks": selected, "chars": len(text)}


def retrieve(question: str, document_id: str | None = None, use_cache: bool = True, user_id: UUID | None = None) -> dict[str, Any]:
    if user_id is None:
        log.warning("retrieve() without user_id uses the legacy unscoped single-user path")
    key = _cache_key(question, document_id, user_id)
    if use_cache:
        cached = get_json(key)
        if cached and "fused" in cached and "query_plan" in cached:
            cached["cached"] = True
            if "images" not in cached:
                cached["images"] = []
            return cached

    plan = understand_query(question)
    vector_ids = hybrid_index.vector_search(question, TOP_K_VECTOR, document_id, user_id)
    bm25_ids = hybrid_index.bm25_search(plan["lexical_query"], TOP_K_BM25, document_id, user_id)
    fused = reciprocal_rank_fusion([vector_ids, bm25_ids])
    candidate_ids = [node_id for node_id, _score in fused[:RERANK_CANDIDATES]]

    texts: list[str] = []
    for node_id in candidate_ids:
        text = hybrid_index.text_for(node_id, user_id)
        if not text:
            row = fetch_node(UUID(node_id), user_id)
            text = (row or {}).get("search_text") or ""
        texts.append(text)
    sim_scores = hybrid_index.similarity(question, texts)
    reranked = list(zip(candidate_ids, sim_scores))
    if plan.get("prefer_tables") and reranked:
        rows = {
            str(row["id"]): row
            for row in fetch_nodes_by_ids([UUID(nid) for nid in candidate_ids], user_id)
        }
        boosted: list[tuple[str, float]] = []
        for node_id, score in reranked:
            meta = rows.get(node_id)
            if meta and meta.get("node_type") == "table":
                score = float(score) + TABLE_RERANK_BONUS
            boosted.append((node_id, float(score)))
        reranked = boosted
    reranked = sorted(reranked, key=lambda item: item[1], reverse=True)

    expansions: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    for node_id, score in reranked:
        expanded = expand_hit(UUID(node_id), plan, user_id)
        if not expanded:
            continue
        section_id = expanded["section_id"]
        if section_id in seen_sections:
            continue
        seen_sections.add(section_id)
        expanded["score"] = float(score)
        expansions.append(expanded)
        if len(expansions) >= TOP_SECTIONS:
            break

    tables = retrieve_tables(reranked, expansions, plan, user_id)
    images = retrieve_images(reranked, expansions, user_id)
    packed = organize_context(plan, expansions, tables)
    payload = {
        "cached": False,
        "query_plan": plan,
        "context": packed["text"],
        "structured": packed["blocks"],
        "sections": expansions,
        "tables": tables,
        "images": images,
        "vector_hits": vector_ids,
        "bm25_hits": bm25_ids,
        "fused": [{"id": node_id, "rrf": score} for node_id, score in fused[:30]],
        "reranked": [{"id": node_id, "score": float(score)} for node_id, score in reranked],
    }
    set_json(key, {k: v for k, v in payload.items() if k != "cached"})
    # Track the cache key for this user to enable invalidation
    if user_id:
        track_cache_key(str(user_id), key)
    return payload


def _clip(text: str, limit: int = 4000) -> dict[str, Any]:
    raw = text or ""
    if len(raw) <= limit:
        return {"text": raw, "truncated": False, "chars": len(raw)}
    return {"text": raw[:limit] + "\n…", "truncated": True, "chars": len(raw)}


def _relation_preview(items: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    preview = []
    for item in items[:limit]:
        preview.append(
            {
                "heading": item.get("heading"),
                "path": item.get("path"),
                "page": item.get("page"),
                "node_type": item.get("node_type"),
            }
        )
    return preview


def build_query_flow(
    question: str,
    document_id: str | None,
    result: dict[str, Any],
    answer: str,
    llm_skipped: bool,
    user_id: UUID | None = None,
) -> dict[str, dict[str, Any]]:
    doc_meta = None
    counts = node_counts(UUID(document_id) if document_id else None, user_id)
    preview: list[dict[str, Any]] = []
    if document_id:
        doc_meta = fetch_document(UUID(document_id), user_id) if user_id else None
        if doc_meta:
            preview = tree_preview(UUID(document_id), limit=40, user_id=user_id)
    tree_lines = [
        f"{item.get('path') or '-'} [{item['node_type']}] {item.get('heading') or ''}"
        for item in preview
    ]
    vector_rows = summarize_nodes(result.get("vector_hits") or [], user_id)
    bm25_rows = summarize_nodes(result.get("bm25_hits") or [], user_id)
    fused_meta = {row["id"]: row for row in vector_rows + bm25_rows}
    fused_rows = []
    for item in result.get("fused") or []:
        meta = fused_meta.get(item["id"], {"id": item["id"]})
        fused_rows.append({**meta, "rrf": item.get("rrf")})
    rerank_rows = []
    for item in result.get("reranked") or []:
        meta = fused_meta.get(item["id"])
        if not meta:
            found = summarize_nodes([item["id"]], user_id)
            meta = found[0] if found else {"id": item["id"]}
        rerank_rows.append({**meta, "score": item.get("score")})

    expansions = result.get("sections") or []
    parents = _relation_preview([item.get("parent") or item for item in expansions])
    siblings: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []
    for item in expansions:
        siblings.extend(_relation_preview(item.get("siblings") or []))
        children.extend(_relation_preview(item.get("children") or []))
    tables = _relation_preview(result.get("tables") or [])
    images = result.get("images") or []
    plan = result.get("query_plan") or understand_query(question)
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
            "key": "understand",
            "title": "Query Understanding",
            "summary": (
                f"type={plan.get('query_type')} · scope={plan.get('scope')} · "
                f"{len(plan.get('concepts') or [])} concepts"
            ),
            "data": plan,
        },
        {
            "key": "vector",
            "title": "pgvector + Sentence-Transformers",
            "summary": f"{len(vector_rows)} vector hits (pgvector)",
            "data": {"hits": vector_rows[:12]},
        },
        {
            "key": "bm25",
            "title": "BM25 Search",
            "summary": f"{len(bm25_rows)} lexical hits",
            "data": {"hits": bm25_rows[:12], "lexical_query": plan.get("lexical_query")},
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
            "key": "hierarchy",
            "title": "Hierarchical Expansion",
            "summary": (
                f"{len(parents)} parents · {len(siblings)} siblings · "
                f"{len(children)} children"
            ),
            "data": {
                "parent": parents,
                "siblings": siblings[:12],
                "children": children[:12],
            },
        },
        {
            "key": "tables",
            "title": "Table Retrieval",
            "summary": f"{len(tables)} tables packed for grounding",
            "data": {"tables": tables},
        },
        {
            "key": "images",
            "title": "Associated Images",
            "summary": f"{len(images)} images associated with retrieved sections",
            "data": {"images": images},
        },
        {
            "key": "context",
            "title": "Context Organizer",
            "summary": (
                f"{len(result.get('structured') or [])} blocks · "
                f"{context_clip['chars']} characters"
            ),
            "data": {
                **context_clip,
                "blocks": result.get("structured") or [],
            },
        },
        {
            "key": "llm",
            "title": "LangChain + Qwen",
            "summary": (
                answer[:180]
                if llm_skipped
                else f"Grounded answer with {OPENAI_MODEL} (Hugging Face router)"
            ),
            "data": {"answer": answer, "skipped": llm_skipped},
        },
    ]
    return {stage["key"]: stage for stage in stages}
