from __future__ import annotations

import gc
import logging
import pickle
import re
import shutil
import time
from typing import Any

from rank_bm25 import BM25Okapi

from app.config import BM25_PATH, EMBEDDING_MODEL, TXTAI_DIR, ensure_data_dirs
from app.db import fetch_all_index_rows

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def _embeddings_config() -> dict[str, Any]:
    return {
        "path": EMBEDDING_MODEL,
        "backend": "app.usearch_ann.USearchANN",
        "content": True,
    }


class HybridIndex:
    def __init__(self) -> None:
        self.embeddings = None
        self.bm25: BM25Okapi | None = None
        self.ids: list[str] = []
        self.document_ids: list[str] = []
        self.tokenized: list[list[str]] = []

    def load_or_rebuild(self) -> None:
        ensure_data_dirs()
        loaded = self._load_txtai() and self._load_bm25()
        if loaded and self.ids:
            log.info("Loaded txtai (USearch) and BM25 indexes (%s nodes)", len(self.ids))
            return
        log.info("Rebuilding indexes from Postgres")
        self.rebuild()

    def _close_embeddings(self) -> None:
        embeddings = self.embeddings
        self.embeddings = None
        if embeddings is None:
            return
        try:
            embeddings.close()
        except Exception as exc:
            log.warning("Could not close txtai embeddings: %s", exc)
        gc.collect()

    def _clear_txtai_dir(self) -> None:
        if not TXTAI_DIR.exists():
            return
        last_error: Exception | None = None
        for attempt in range(8):
            try:
                shutil.rmtree(TXTAI_DIR)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.25 * (attempt + 1))
                gc.collect()
        if last_error:
            raise last_error

    def rebuild(self) -> None:
        ensure_data_dirs()
        rows = fetch_all_index_rows()
        self.ids = [str(row["id"]) for row in rows]
        self.document_ids = [str(row["document_id"]) for row in rows]
        texts = [row["search_text"] or "" for row in rows]
        self.tokenized = [tokenize(text) for text in texts]
        self.bm25 = BM25Okapi(self.tokenized) if self.tokenized else None
        self._save_bm25()

        from txtai.embeddings import Embeddings

        self._close_embeddings()
        self._clear_txtai_dir()
        ensure_data_dirs()
        self.embeddings = Embeddings(_embeddings_config())
        if rows:
            records = [
                {
                    "id": str(row["id"]),
                    "text": row["search_text"],
                    "document_id": str(row["document_id"]),
                }
                for row in rows
            ]
            self.embeddings.index(records)
            self.embeddings.save(str(TXTAI_DIR))
        log.info("Indexed %s nodes (txtai/USearch + BM25)", len(self.ids))

    def _load_txtai(self) -> bool:
        config_path = TXTAI_DIR / "config"
        if not config_path.exists() and not (TXTAI_DIR / "embeddings").exists():
            if not any(TXTAI_DIR.glob("*")):
                return False
        try:
            from txtai.embeddings import Embeddings

            self.embeddings = Embeddings()
            self.embeddings.load(str(TXTAI_DIR))
            return True
        except Exception as exc:
            log.warning("Could not load txtai index: %s", exc)
            self.embeddings = None
            return False

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
        if self.embeddings is None:
            return []
        fetch = max(limit * 4, limit)
        try:
            if document_id:
                sql = (
                    "select id, score from txtai where similar(:query) "
                    "and document_id = :document_id limit :limit"
                )
                hits = self.embeddings.search(
                    sql,
                    limit=fetch,
                    parameters={"query": query, "document_id": document_id, "limit": fetch},
                )
            else:
                hits = self.embeddings.search(query, fetch)
        except Exception as exc:
            log.warning("Filtered vector search failed (%s); using unfiltered search", exc)
            try:
                hits = self.embeddings.search(query, fetch)
            except Exception:
                return []
        ids: list[str] = []
        for hit in hits or []:
            node_id = str(hit["id"] if isinstance(hit, dict) else hit[0])
            ids.append(node_id)
        if document_id:
            allowed = {
                nid for nid, doc in zip(self.ids, self.document_ids) if doc == document_id
            }
            ids = [nid for nid in ids if nid in allowed]
        return ids[:limit]

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
        if self.embeddings is not None:
            try:
                ranked = self.embeddings.similarity(query, texts)
                scores = [0.0] * len(texts)
                for index, score in ranked:
                    scores[int(index)] = float(score)
                return scores
            except Exception as exc:
                log.warning("txtai similarity failed: %s", exc)
        return [0.0] * len(texts)

    def text_for(self, node_id: str) -> str:
        if self.embeddings is None:
            return ""
        try:
            rows = self.embeddings.search(
                "select id, text from txtai where id = :id",
                parameters={"id": node_id},
            )
            if rows:
                row = rows[0]
                return row["text"] if isinstance(row, dict) else ""
        except Exception:
            pass
        return ""


hybrid_index = HybridIndex()
