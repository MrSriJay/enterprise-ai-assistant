"""Second-stage ranking after dense and sparse scores are fused.

The reranker adds a small bonus when query terms land in the title or when the
document is newer. It does not call another model. A cross-encoder can replace
``rerank`` later without changing the retriever's contract.
"""

from __future__ import annotations

from datetime import date

from app.clock import app_today
from app.retrieval.textutil import tokenize


def rerank(query: str, hits: list[dict], limit: int) -> list[dict]:
    query_terms = set(tokenize(query))
    today = app_today()
    ranked: list[dict] = []
    for hit in hits:
        title_terms = set(tokenize(hit.get("title") or ""))
        if query_terms:
            title_overlap = len(query_terms & title_terms) / len(query_terms)
        else:
            title_overlap = 0.0
        recency = _recency(hit.get("created_date") or "", today)
        score = 0.8 * float(hit.get("hybrid_score") or 0) + 0.15 * title_overlap + 0.05 * recency
        if (hit.get("doc_id") or "").lower() in query.lower():
            score += 1.0
        updated = dict(hit)
        updated["rerank_score"] = round(score, 4)
        ranked.append(updated)
    ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
    return ranked[:limit]


def _recency(created: str, today: date) -> float:
    try:
        written = date.fromisoformat(created)
    except ValueError:
        return 0.0
    age_days = max(0, (today - written).days)
    return max(0.0, 1.0 - min(age_days, 730) / 730)
