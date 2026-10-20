"""
pgvector-based vector search module for industrial standard vector operations.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sentence_transformers import SentenceTransformer

from app.config import EMBEDDING_MODEL
from app.repositories import upsert_embedding, upsert_embeddings_batch, vector_search

log = logging.getLogger(__name__)


class EmbeddingModel:
    """Wrapper for sentence-transformers embedding model."""
    
    def __init__(self, model_name: str = EMBEDDING_MODEL):
        self.model_name = model_name
        self.model: SentenceTransformer | None = None
        self._load_model()
    
    def _load_model(self) -> None:
        try:
            self.model = SentenceTransformer(self.model_name)
            log.info("Loaded embedding model: %s", self.model_name)
        except Exception as exc:
            log.error("Failed to load embedding model %s: %s", self.model_name, exc)
            raise
    
    def encode(self, text: str | list[str]) -> list[float] | list[list[float]]:
        """Encode text to embedding vector(s)."""
        if self.model is None:
            raise RuntimeError("Embedding model not loaded")
        
        if isinstance(text, str):
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        else:
            embeddings = self.model.encode(text, convert_to_numpy=True)
            return embeddings.tolist()
    
    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to embedding vectors."""
        if self.model is None:
            raise RuntimeError("Embedding model not loaded")
        
        embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return embeddings.tolist()


class VectorStore:
    """pgvector-based vector store for industrial standard vector operations."""
    
    def __init__(self, embedding_model: EmbeddingModel | None = None):
        self.embedding_model = embedding_model or EmbeddingModel()
    
    def add_document(self, node_id: UUID, text: str) -> None:
        """Add a single document to the vector store."""
        try:
            embedding = self.embedding_model.encode(text)
            upsert_embedding(node_id, embedding)
        except Exception as exc:
            log.error("Failed to add document %s: %s", node_id, exc)
            raise
    
    def add_documents_batch(self, documents: list[tuple[UUID, str]]) -> None:
        """Add multiple documents to the vector store in batch."""
        if not documents:
            return
        
        try:
            texts = [text for _, text in documents]
            embeddings = self.embedding_model.encode_batch(texts)
            
            embeddings_data = [
                (node_id, embedding)
                for (node_id, _), embedding in zip(documents, embeddings)
            ]
            upsert_embeddings_batch(embeddings_data)
            log.info("Added %d documents to vector store", len(documents))
        except Exception as exc:
            log.error("Failed to add batch documents: %s", exc)
            raise
    
    def search(
        self,
        query: str,
        limit: int = 20,
        document_id: UUID | None = None,
        user_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        """Search for similar documents using vector similarity."""
        try:
            query_embedding = self.embedding_model.encode(query)
            results = vector_search(query_embedding, limit, document_id, user_id)
            return results
        except Exception as exc:
            log.error("Vector search failed: %s", exc)
            return []
    
    def similarity(self, query: str, texts: list[str]) -> list[float]:
        """Compute similarity scores between query and texts."""
        if not texts:
            return []
        
        try:
            query_embedding = self.embedding_model.encode(query)
            text_embeddings = self.embedding_model.encode_batch(texts)
            
            from scipy.spatial.distance import cosine
            scores = [
                1.0 - cosine(query_embedding, text_embedding)
                for text_embedding in text_embeddings
            ]
            return scores
        except Exception as exc:
            log.error("Similarity computation failed: %s", exc)
            return [0.0] * len(texts)


# Global instance
_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Get or create the global vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
