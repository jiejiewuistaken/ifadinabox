from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .ingestion import Chunk


VectorStoreSource = Literal["user", "internal"]


@dataclass
class SearchHit:
    score: float
    chunk: dict[str, Any]


class LocalTfidfVectorStore:
    """
    File-based “vector DB” using TF-IDF vectors.
    Persisted in a folder containing:
      - chunks.jsonl
      - vectorizer.joblib
      - matrix.joblib  (sparse CSR)
    """

    def __init__(self, dir_path: Path) -> None:
        self.dir_path = dir_path
        self.chunks_path = dir_path / "chunks.jsonl"
        self.vectorizer_path = dir_path / "vectorizer.joblib"
        self.matrix_path = dir_path / "matrix.joblib"

        self._chunks: list[dict[str, Any]] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix: csr_matrix | None = None

    def reset(self) -> None:
        self.dir_path.mkdir(parents=True, exist_ok=True)
        if self.chunks_path.exists():
            self.chunks_path.unlink()
        if self.vectorizer_path.exists():
            self.vectorizer_path.unlink()
        if self.matrix_path.exists():
            self.matrix_path.unlink()
        self._chunks = []
        self._vectorizer = None
        self._matrix = None

    def add_chunks(self, chunks: list[Chunk]) -> None:
        self.dir_path.mkdir(parents=True, exist_ok=True)
        with self.chunks_path.open("a", encoding="utf-8") as f:
            for c in chunks:
                obj = {
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "source": c.source,
                    "filename": c.filename,
                    "page": c.page,
                    "text": c.text,
                    "meta": c.meta,
                }
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def build(self) -> None:
        if not self.chunks_path.exists():
            raise RuntimeError("No chunks to build vector store.")

        chunks: list[dict[str, Any]] = []
        texts: list[str] = []
        with self.chunks_path.open("r", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                chunks.append(obj)
                texts.append(obj["text"])

        vectorizer = TfidfVectorizer(stop_words="english", max_features=50000)
        matrix = vectorizer.fit_transform(texts)

        joblib.dump(vectorizer, self.vectorizer_path)
        joblib.dump(matrix, self.matrix_path)

        self._chunks = chunks
        self._vectorizer = vectorizer
        self._matrix = matrix

    def load(self) -> None:
        self._vectorizer = joblib.load(self.vectorizer_path)
        self._matrix = joblib.load(self.matrix_path)
        chunks: list[dict[str, Any]] = []
        with self.chunks_path.open("r", encoding="utf-8") as f:
            for line in f:
                chunks.append(json.loads(line))
        self._chunks = chunks

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        source_filter: VectorStoreSource | None = None,
        scope_filter: set[str] | None = None,
    ) -> list[SearchHit]:
        if self._vectorizer is None or self._matrix is None or not self._chunks:
            self.load()

        assert self._vectorizer is not None
        assert self._matrix is not None

        q_vec = self._vectorizer.transform([query])
        sims = cosine_similarity(q_vec, self._matrix).ravel()

        idxs = np.argsort(-sims)[: max(top_k * 3, top_k)]
        hits: list[SearchHit] = []
        for i in idxs:
            c = self._chunks[int(i)]
            if source_filter and c.get("source") != source_filter:
                continue
            if scope_filter:
                meta = c.get("meta") or {}
                scopes = set(meta.get("scopes") or ["public"])
                if not scopes.intersection(scope_filter):
                    continue
            hits.append(SearchHit(score=float(sims[int(i)]), chunk=c))
            if len(hits) >= top_k:
                break
        return hits

