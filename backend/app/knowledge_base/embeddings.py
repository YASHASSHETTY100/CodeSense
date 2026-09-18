"""Embeddings: sentence-transformers when installed+requested, else TF-IDF fallback.

TF-IDF fallback is deterministic, offline, and good enough for keyword-heavy code
retrieval (function names, endpoints, business terms). Vectors stored as JSON text
so sqlite + postgres both work without pgvector.
"""
from __future__ import annotations
import json, math, re
import numpy as np

_TOKEN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_./-]*")


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)][:2000]


class TfidfEmbedder:
    def __init__(self, dim: int = 512):
        self.dim = dim
        self.df: dict[str, int] = {}
        self.n_docs = 0

    def _hash(self, tok: str) -> int:
        return (abs(hash(tok)) % (self.dim - 1)) + 1

    def fit(self, docs: list[str]) -> None:
        self.n_docs = max(1, len(docs))
        df: dict[str, int] = {}
        for d in docs:
            for t in set(tokens(d)):
                df[t] = df.get(t, 0) + 1
        self.df = df

    def embed(self, text: str) -> list[float]:
        v = np.zeros(self.dim)
        toks = tokens(text)
        if not toks:
            return v.tolist()
        import collections
        tf = collections.Counter(toks)
        for t, c in tf.items():
            idf = math.log((1 + self.n_docs) / (1 + self.df.get(t, 0))) + 1.0
            v[self._hash(t)] += (c / len(toks)) * idf
        n = np.linalg.norm(v)
        if n > 0:
            v = v / n
        return v.tolist()


class STEmbedder:
    """Wrapper around sentence-transformers (optional dependency)."""
    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model)

    def fit(self, docs: list[str]) -> None:
        pass

    def embed(self, text: str) -> list[float]:
        v = self.model.encode(text[:4000], normalize_embeddings=True)
        return [float(x) for x in v]


def get_embedder(backend: str = "tfidf"):
    if backend == "st":
        try:
            return STEmbedder()
        except Exception:
            pass
    return TfidfEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    import numpy as np
    va, vb = np.array(a), np.array(b)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(va @ vb / (na * nb))
