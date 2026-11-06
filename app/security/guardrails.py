"""Output checks: citations, obvious PII, and the bank's name.

The guardrail does not try to decide whether prose is eloquent. It checks
whether the answer is allowed to cite the documents it cites, and whether it
leaks a card number, a national id, or a planted canary the caller cannot see.
"""

from __future__ import annotations

import re

from app.config import get_settings

CITATION_RE = re.compile(r"\[doc:([A-Za-z0-9_-]+)\]")
CARD_RE = re.compile(r"\b\d{13,19}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CANARIES = ("SYSTEM-PROMPT-DUMP-991", "CANARY-RESTRICTED-KEY-7741", "BONUS-POOL-CONFIDENTIAL-442")

CITED_ROUTES = {"retrieve", "research", "analytics"}


def extract_citation_ids(text: str) -> list[str]:
    return CITATION_RE.findall(text or "")


def validate_answer(
    answer: str,
    *,
    route: str,
    retrieved: list[dict],
    grounded_answer: str,
) -> dict:
    """Return the answer that is safe to show, plus a validation report."""

    allowed_ids = {item["doc_id"] for item in retrieved}
    text = (answer or "").strip()
    issues: list[str] = []

    text, card_hits = CARD_RE.subn("[redacted-number]", text)
    text, ssn_hits = SSN_RE.subn("[redacted-id]", text)
    if card_hits or ssn_hits:
        issues.append("redacted sensitive numbers")

    for canary in CANARIES:
        if canary in text and not _canary_allowed(canary, allowed_ids):
            text = text.replace(canary, "[redacted]")
            issues.append(f"removed {canary}")

    cited = extract_citation_ids(text)
    unknown = [item for item in cited if item not in allowed_ids]
    if unknown:
        issues.append("removed unsupported citations: " + ", ".join(unknown))
        for item in unknown:
            text = text.replace(f"[doc:{item}]", "")

    needs_citation = route in CITED_ROUTES and bool(retrieved)
    known = [item for item in extract_citation_ids(text) if item in allowed_ids]
    repaired = False
    if needs_citation and not known:
        issues.append("replaced an uncited answer with the grounded draft")
        text = (grounded_answer or "").strip() or _insufficient(route)
        repaired = True
    elif not text.strip():
        issues.append("replaced an empty answer")
        text = (grounded_answer or "").strip() or _insufficient(route)
        repaired = True

    company = get_settings().company_name
    if re.search(r"\b(as an ai language model|i am chatgpt)\b", text, re.I):
        text = f"I am the internal assistant for {company}.\n\n" + text
        issues.append("restored the bank identity")

    return {
        "status": "repaired" if issues else "passed",
        "issues": issues,
        "repaired": repaired,
        "answer": text.strip(),
        "citations": citations_for(text, retrieved),
    }


def citations_for(text: str, retrieved: list[dict]) -> list[dict]:
    wanted = set(extract_citation_ids(text))
    citations: list[dict] = []
    seen: set[str] = set()
    for hit in retrieved:
        doc_id = hit["doc_id"]
        if doc_id not in wanted or doc_id in seen:
            continue
        seen.add(doc_id)
        snippet = " ".join((hit.get("text") or "").split())[:240]
        citations.append(
            {
                "doc_id": doc_id,
                "chunk_id": hit.get("chunk_id", doc_id),
                "title": hit.get("title", doc_id),
                "department": hit.get("department", ""),
                "document_type": hit.get("document_type", ""),
                "access_level": hit.get("access_level", ""),
                "created_date": hit.get("created_date", ""),
                "snippet": snippet,
                "score": round(float(hit.get("rerank_score") or hit.get("hybrid_score") or 0), 4),
            }
        )
    return citations


def _canary_allowed(canary: str, allowed_ids: set[str]) -> bool:
    allowed = {
        "CANARY-RESTRICTED-KEY-7741": "sec-key-ceremony",
        "BONUS-POOL-CONFIDENTIAL-442": "hr-comp-2026",
    }
    doc_id = allowed.get(canary)
    if doc_id is None:
        return False
    return doc_id in allowed_ids


def _insufficient(route: str) -> str:
    if route in CITED_ROUTES:
        return (
            "I couldn't find enough evidence in the documents your role is allowed to read. "
            "I won't guess."
        )
    return "I don't have a grounded answer for that."
