from __future__ import annotations

import logging
import pickle
import re
from typing import Any
from uuid import UUID

from rank_bm25 import BM25Okapi

from app.config import BM25_PATH, ensure_data_dirs
from app.db import fetch_all_index_rows
from app.pgvector_search import get_vector_store

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


class HybridIndex:
    def __init__(self) -> None:
        self.vector_store = get_vector_store()
        self.bm25: BM25Okapi | None = None
        self.ids: list[str] = []
        self.document_ids: list[str] = []
        self.tokenized: list[list[str]] = []

    def load_or_rebuild(self) -> None:
        ensure_data_dirs()
        loaded = self._load_bm25()
        if loaded and self.ids:
            log.info("Loaded BM25 index (%s nodes)", len(self.ids))
            return
        log.info("Rebuilding indexes from Postgres")
        self.rebuild()

    def rebuild(self) -> None:
        ensure_data_dirs()
        rows = fetch_all_index_rows()
        self.ids = [str(row["id"]) for row in rows]
        self.document_ids = [str(row["document_id"]) for row in rows]
        texts = [row["search_text"] or "" for row in rows]
        self.tokenized = [tokenize(text) for text in texts]
        self.bm25 = BM25Okapi(self.tokenized) if self.tokenized else None
        self._save_bm25()

        # Rebuild vector embeddings in pgvector
        if rows:
            documents = [
                (UUID(str(row["id"])), row["search_text"] or "")
                for row in rows
            ]
            self.vector_store.add_documents_batch(documents)
        log.info("Indexed %s nodes (pgvector + BM25)", len(self.ids))

    def _load_bm25(self) -> bool:
        if not BM25_PATH.exists():
            return False
        try:
            with BM25_PATH.open("rb") as handle:
                payload = pickle.load(handle)
            self.ids = payload["ids"]
            self.document_ids = payload["document_ids"]
            self.tokenized = payload["tokenized"]
            self.bm25 = BM25Okapi(self.tokenized) if self.tokenized else None
            return True
        except Exception as exc:
            log.warning("Could not load BM25 pickle: %s", exc)
            return False

    def _save_bm25(self) -> None:
        with BM25_PATH.open("wb") as handle:
            pickle.dump(
                {
                    "ids": self.ids,
                    "document_ids": self.document_ids,
                    "tokenized": self.tokenized,
                },
                handle,
            )

    def vector_search(self, query: str, limit: int, document_id: str | None = None) -> list[str]:
        try:
            doc_uuid = UUID(document_id) if document_id else None
            results = self.vector_store.search(query, limit, doc_uuid)
            return [result["id"] for result in results]
        except Exception as exc:
            log.warning("Vector search failed: %s", exc)
            return []

    def bm25_search(self, query: str, limit: int, document_id: str | None = None) -> list[str]:
        if not self.bm25 or not self.ids:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        ids: list[str] = []
        for index in ranked:
            if scores[index] <= 0:
                break
            if document_id and self.document_ids[index] != document_id:
                continue
            ids.append(self.ids[index])
            if len(ids) >= limit:
                break
        return ids

    def similarity(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        try:
            return self.vector_store.similarity(query, texts)
        except Exception as exc:
            log.warning("Similarity computation failed: %s", exc)
            return [0.0] * len(texts)

    def text_for(self, node_id: str) -> str:
        try:
            uuid = UUID(node_id)
            from app.db import fetch_node
            node = fetch_node(uuid)
            if node:
                return node.get("search_text") or node.get("text") or ""
        except Exception as exc:
            log.warning("Failed to fetch text for node %s: %s", node_id, exc)
        return ""


hybrid_index = HybridIndex()
