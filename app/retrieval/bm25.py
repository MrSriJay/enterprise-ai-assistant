"""A small BM25 ranker.

Scores are computed over the whole corpus and then masked to the metadata
candidates. The saturated ``score / (score + 1.5)`` form is what hybrid search
mixes with cosine, so one very long hit cannot force every other score to zero.
"""

from __future__ import annotations

import math

from app.retrieval.textutil import tokenize


class BM25Index:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.tokens = [tokenize(document) for document in documents]
        self.doc_count = len(self.tokens)
        self.term_freq: list[dict[str, int]] = []
        self.doc_freq: dict[str, int] = {}
        self.lengths: list[int] = []
        for tokens in self.tokens:
            counts: dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            self.term_freq.append(counts)
            self.lengths.append(len(tokens) or 1)
            for token in counts:
                self.doc_freq[token] = self.doc_freq.get(token, 0) + 1
        self.avg_length = (sum(self.lengths) / self.doc_count) if self.doc_count else 1.0

    def score(self, query: str, index: int) -> float:
        if not self.doc_count:
            return 0.0
        total = 0.0
        length = self.lengths[index]
        seen: set[str] = set()
        for token in tokenize(query):
            if token in seen or token not in self.term_freq[index]:
                seen.add(token)
                continue
            seen.add(token)
            frequency = self.term_freq[index][token]
            df = self.doc_freq.get(token, 0)
            idf = math.log(1.0 + (self.doc_count - df + 0.5) / (df + 0.5))
            denominator = frequency + self.k1 * (1 - self.b + self.b * length / self.avg_length)
            total += idf * (frequency * (self.k1 + 1)) / denominator
        return total

    @staticmethod
    def saturate(score: float) -> float:
        if score <= 0:
            return 0.0
        return score / (score + 1.5)
