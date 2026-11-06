"""Token helpers shared by BM25, hashing embeddings, and the reranker."""

from __future__ import annotations

import re

STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "to",
    "and",
    "for",
    "in",
    "on",
    "is",
    "are",
    "was",
    "were",
    "be",
    "with",
    "that",
    "this",
    "these",
    "those",
    "by",
    "from",
    "or",
    "as",
    "at",
    "it",
    "its",
    "into",
    "during",
    "over",
}


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in STOPWORDS and len(token) > 1
    ]
