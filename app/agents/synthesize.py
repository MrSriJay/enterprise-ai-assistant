"""Turn retrieved documents into a cited answer without calling a model."""

from __future__ import annotations

import re

from app.retrieval.textutil import tokenize


def evidence_snippet(text: str, query: str, limit: int = 280) -> str:
    body = text.split("\n", 1)[-1] if "\n" in text else text
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", body) if part.strip()]
    terms = set(tokenize(query))
    if not sentences:
        return " ".join(body.split())[:limit]

    def score(sentence: str) -> int:
        return len(terms & set(tokenize(sentence)))

    ordered = sorted(sentences, key=score, reverse=True)
    chosen: list[str] = []
    size = 0
    for sentence in ordered:
        if score(sentence) == 0 and chosen:
            continue
        chosen.append(sentence)
        size += len(sentence)
        if len(chosen) == 2 or size >= limit:
            break
    snippet = " ".join(chosen) if chosen else ordered[0]
    return " ".join(snippet.split())[:limit]


def answer_from_hits(query: str, hits: list[dict]) -> str:
    if not hits:
        return ""
    lines = ["Here is what the documents your role can read say:", ""]
    seen: set[str] = set()
    for hit in hits:
        doc_id = hit["doc_id"]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        snippet = evidence_snippet(hit.get("text") or "", query)
        lines.append(
            f"- {hit.get('title')} ({hit.get('created_date')}, {hit.get('document_type')}): "
            f"{snippet} [doc:{doc_id}]"
        )
        if len(seen) == 4:
            break
    return "\n".join(lines)


def render_mcp(result: dict | None) -> str:
    result = result or {}
    if result.get("error") == "invalid_parameters":
        return "I did not run the enterprise tool because its parameters failed validation."
    data = result.get("data") or []
    if result.get("error") == "mcp_unavailable" and not data:
        return "The enterprise MCP server is unavailable, and the in-process fallback is turned off. I cannot answer that lookup right now."
    lines: list[str] = []
    if result.get("degraded"):
        lines.append(
            "The MCP server was unreachable, so this answer uses the in-process copy of the same enterprise data."
        )
    if not data:
        lines.append("The enterprise tool returned no matching records.")
        return "\n".join(lines)
    lines.append(f"Tool `{result.get('tool', 'enterprise')}` returned:")
    for row in data:
        rendered = ", ".join(f"{key}: {value}" for key, value in row.items())
        lines.append(f"- {rendered}")
    return "\n".join(lines)
