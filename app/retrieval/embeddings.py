"""Dense vectors.

The default embedder hashes tokens into a fixed vector. It needs no model
download, so hybrid search works offline. When ``USE_OPENAI_EMBEDDINGS`` is on,
the same call sites send ``text-embedding-3-small`` instead and the index is
rebuilt because the dimension changes.
"""

from __future__ import annotations

import hashlib

import numpy as np

from app.config import get_settings
from app.retrieval.textutil import tokenize


def embed_texts(texts: list[str]) -> np.ndarray:
    settings = get_settings()
    if settings.openai_embeddings_ready:
        return _openai_embed(texts)
    return hashing_embed(texts, settings.embedding_dim)


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]


def hashing_embed(texts: list[str], dim: int) -> np.ndarray:
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for row, text in enumerate(texts):
        tokens = tokenize(text)
        features = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "little")
            index = bucket % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vectors[row, index] += sign
    return _normalize(vectors)


def embedding_name() -> str:
    settings = get_settings()
    if settings.openai_embeddings_ready:
        return f"openai:{settings.embedding_model}"
    return f"hashing:{settings.embedding_dim}"


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _openai_embed(texts: list[str]) -> np.ndarray:
    import httpx

    settings = get_settings()
    vectors: list[list[float]] = []
    with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
        for start in range(0, len(texts), 64):
            batch = texts[start : start + 64]
            response = client.post(
                f"{settings.openai_base_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.embedding_model, "input": batch},
            )
            response.raise_for_status()
            data = response.json()["data"]
            data.sort(key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in data)
    return _normalize(np.asarray(vectors, dtype=np.float32))
