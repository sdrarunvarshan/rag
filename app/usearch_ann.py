"""
txtai ANN backend backed by the usearch package.
"""

from __future__ import annotations

import numpy as np
from usearch.index import Index
from txtai.ann.base import ANN


class USearchANN(ANN):
    """Approximate nearest-neighbor index using USearch (cosine)."""

    def __init__(self, config):
        super().__init__(config)
        self.backend: Index | None = None
        self._path: str | None = None

    def load(self, path):
        self._path = path
        self.backend = Index()
        self.backend.load(path)

    def index(self, embeddings):
        ndim = int(embeddings.shape[1])
        self.backend = Index(ndim=ndim, metric="cos")
        keys = np.arange(embeddings.shape[0], dtype=np.int64)
        self.backend.add(keys, embeddings)
        self.config["offset"] = embeddings.shape[0]
        self.config["dimensions"] = ndim
        self.metadata({"backend": "usearch"})

    def append(self, embeddings):
        if self.backend is None:
            self.index(embeddings)
            return
        start = int(self.config.get("offset", 0))
        keys = np.arange(start, start + embeddings.shape[0], dtype=np.int64)
        self.backend.add(keys, embeddings)
        self.config["offset"] = start + embeddings.shape[0]
        self.metadata()

    def delete(self, ids):
        if self.backend is None:
            return
        for node_id in ids:
            try:
                self.backend.remove(int(node_id))
            except Exception:
                pass

    def search(self, queries, limit):
        if self.backend is None or len(self.backend) == 0:
            array = np.asarray(queries)
            count = 1 if array.ndim == 1 else len(array)
            return [[] for _ in range(count)]

        array = np.asarray(queries)
        if array.ndim == 1:
            return [self._to_scores(self.backend.search(array, count=limit))]

        matches = self.backend.search(array, count=limit)
        if hasattr(matches, "counts"):
            return [self._to_scores(matches[row]) for row in range(len(matches))]
        return [self._to_scores(matches)]

    def count(self):
        return len(self.backend) if self.backend is not None else 0

    def close(self):
        self.backend = None
        self._path = None

    def save(self, path):
        if self.backend is not None:
            self.backend.save(path)

    @staticmethod
    def _to_scores(matches) -> list[tuple[int, float]]:
        keys = matches.keys
        distances = matches.distances
        return [
            (int(key), max(0.0, 1.0 - float(distance)))
            for key, distance in zip(keys, distances)
        ]
