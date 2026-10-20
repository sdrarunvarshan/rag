from __future__ import annotations

import logging
import pickle
import re
from typing import Any
from uuid import UUID

from rank_bm25 import BM25Okapi

from app.config import BM25_PATH, ensure_data_dirs
from app.db import fetch_all_index_rows
from app.vector.pgvector_search import get_vector_store

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
        self.version: str | None = None

    def load_or_rebuild(self) -> None:
        ensure_data_dirs()
        loaded = self._load_bm25()
        if loaded and self.ids:
            # Calculate current corpus fingerprint
            current_fingerprint = self._get_corpus_fingerprint()
            # Compare with loaded version
            if self.version == current_fingerprint:
                log.info("Loaded BM25 index (%s nodes, version matches)", len(self.ids))
                return
            else:
                log.info("BM25 index version mismatch: stored=%s, current=%s - rebuilding", 
                         self.version, current_fingerprint)
        log.info("Rebuilding BM25 index from Postgres")
        self.rebuild_bm25()

    def rebuild_bm25(self, user_id: UUID | None = None) -> None:
        """
        Rebuild BM25 index from PostgreSQL.

        IMPORTANT: The shared BM25 index (BM25_PATH) must include ALL users' nodes
        to prevent cross-tenant isolation bugs. Tenant filtering is applied during
        search (bm25_search), not during index construction.

        Args:
            user_id: Ignored for the shared index. Always indexes all users' nodes.
                    This parameter is kept for API compatibility but not used.
        """
        ensure_data_dirs()
        # Always fetch all users' nodes for the shared index
        # Tenant filtering happens during search, not during index building
        rows = fetch_all_index_rows(user_id=None)
        self.ids = [str(row["id"]) for row in rows]
        self.document_ids = [str(row["document_id"]) for row in rows]
        texts = [row["search_text"] or "" for row in rows]
        self.tokenized = [tokenize(text) for text in texts]
        self.bm25 = BM25Okapi(self.tokenized) if self.tokenized else None
        self._save_bm25()
        log.info("Indexed %s nodes (BM25, all users)", len(self.ids))

    def rebuild(self) -> None:
        self.rebuild_bm25()

        # Rebuild vector embeddings in pgvector
        rows = fetch_all_index_rows()
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
            self.version = payload.get("version")
            self.bm25 = BM25Okapi(self.tokenized) if self.tokenized else None
            log.info("Loaded BM25 index (version: %s)", self.version)
            return True
        except Exception as exc:
            log.warning("Could not load BM25 pickle: %s", exc)
            return False

    def _save_bm25(self) -> None:
        # Write to temporary file first, then atomically replace
        temp_path = BM25_PATH.with_suffix(".pkl.tmp")
        with temp_path.open("wb") as handle:
            pickle.dump(
                {
                    "ids": self.ids,
                    "document_ids": self.document_ids,
                    "tokenized": self.tokenized,
                    "version": self._get_corpus_fingerprint(),  # Save corpus fingerprint
                },
                handle,
            )
        # Atomic replace
        temp_path.replace(BM25_PATH)
        log.info("BM25 index saved atomically to %s", BM25_PATH)
    
    def _get_version(self) -> str:
        """
        Generate a content-based version identifier for the index.

        Uses a hash of all node IDs, document IDs, and text content to detect changes
        even when IDs remain the same but text changes.
        """
        import hashlib
        # Sort for deterministic hashing
        sorted_ids = sorted(self.ids)
        sorted_doc_ids = sorted(self.document_ids)
        content = f"{','.join(sorted_ids)}-{','.join(sorted_doc_ids)}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _get_corpus_fingerprint(self) -> str:
        """
        Generate a corpus fingerprint including text content to detect stale indexes.
        
        This hashes node IDs, document IDs, and text content to ensure that
        if any node's text changes, the fingerprint changes and triggers a rebuild.
        
        Uses JSON serialization for unambiguous fingerprinting (no delimiter conflicts).
        """
        import hashlib
        import json
        
        # Fetch all indexed rows with text content
        rows = fetch_all_index_rows(user_id=None)
        
        # Sort for deterministic hashing
        sorted_rows = sorted(rows, key=lambda r: (str(r["id"]), str(r["document_id"])))
        
        # Build fingerprint using JSON serialization (unambiguous)
        fingerprint_data = [
            {
                "id": str(row["id"]),
                "document_id": str(row["document_id"]),
                "text": (row["search_text"] or "")[:100]
            }
            for row in sorted_rows
        ]
        
        content = json.dumps(fingerprint_data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def vector_search(self, query: str, limit: int, document_id: str | None = None, user_id: UUID | None = None) -> list[str]:
        try:
            doc_uuid = UUID(document_id) if document_id else None
            results = self.vector_store.search(query, limit, doc_uuid, user_id)
            return [result["id"] for result in results]
        except Exception as exc:
            log.warning("Vector search failed: %s", exc)
            return []

    def bm25_search(self, query: str, limit: int, document_id: str | None = None, user_id: UUID | None = None) -> list[str]:
        if not self.bm25 or not self.ids:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        ids: list[str] = []
        
        # If user_id is provided, fetch the user's document_ids for ownership filtering
        # This applies both for corpus-wide searches AND document-scoped searches
        user_document_ids: set[str] = set()
        if user_id:
            from app.db import connect
            with connect() as conn:
                rows = conn.execute(
                    "SELECT id FROM documents WHERE user_id = %s",
                    (user_id,),
                ).fetchall()
                user_document_ids = {str(row["id"]) for row in rows}
        
        for index in ranked:
            if scores[index] <= 0:
                break
            # Filter by document_id if specified
            if document_id and self.document_ids[index] != document_id:
                continue
            # Filter by user_id if specified (applies to both corpus-wide and document-scoped)
            if user_id and self.document_ids[index] not in user_document_ids:
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
