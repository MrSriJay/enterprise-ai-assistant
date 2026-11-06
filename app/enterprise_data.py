"""Dummy operational systems exposed through the MCP server.

These records are intentionally separate from the document index. The agent
uses them for "who is on call" and "what is open in the incident system"
questions, not as a substitute for the written post-incident reports.
"""

from __future__ import annotations

import re

EMPLOYEES: list[dict] = [
    {
        "name": "Ada Lovelace",
        "team": "Payments Engineering",
        "title": "Staff Engineer",
        "on_call": "primary",
        "service": "payment-gateway",
    },
    {
        "name": "Grace Hopper",
        "team": "Platform",
        "title": "Engineering Manager",
        "on_call": "secondary",
        "service": "settlement-batch",
    },
    {
        "name": "Katherine Johnson",
        "team": "Retail Banking",
        "title": "Product Owner",
        "on_call": "none",
        "service": "mobile-wallet",
    },
    {
        "name": "Alan Turing",
        "team": "Security",
        "title": "Security Engineer",
        "on_call": "security",
        "service": "card-switch",
    },
]

SERVICES: list[dict] = [
    {"name": "payment-gateway", "tier": "critical", "owner": "Ada Lovelace", "description": "Authorizes card and wallet payments."},
    {"name": "settlement-batch", "tier": "critical", "owner": "Grace Hopper", "description": "Posts ACH and card settlement files."},
    {"name": "card-switch", "tier": "critical", "owner": "Alan Turing", "description": "Routes authorization traffic to schemes."},
    {"name": "mobile-wallet", "tier": "high", "owner": "Katherine Johnson", "description": "Customer wallet inside the Harborline app."},
]

OPERATIONAL_INCIDENTS: list[dict] = [
    {"id": "MCP-1001", "service": "payment-gateway", "status": "open", "severity": "sev-2", "summary": "Elevated gateway timeouts in the last hour."},
    {"id": "MCP-1002", "service": "card-switch", "status": "resolved", "severity": "sev-3", "summary": "Certificate warning cleared after rotation."},
    {"id": "MCP-1003", "service": "settlement-batch", "status": "open", "severity": "sev-3", "summary": "Tonight's ACH file is waiting on disk space."},
]

_STOP = {"the", "a", "an", "of", "to", "and", "for", "in", "on", "is", "who", "what", "are", "with", "for"}


def search_employees(query: str) -> list[dict]:
    terms = _terms(query)
    ranked: list[tuple[int, dict]] = []
    for row in EMPLOYEES:
        score = _overlap(terms, row)
        if "on-call" in query.lower() or "on call" in query.lower():
            if row.get("on_call") not in {"", "none"} and "payment" in query.lower() and "payment" in row["team"].lower():
                score += 2
            elif row.get("on_call") not in {"", "none"} and score:
                score += 1
        if score:
            ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in ranked[:3]]


def search_services(query: str) -> list[dict]:
    terms = _terms(query)
    if not terms:
        return list(SERVICES)
    ranked = []
    for row in SERVICES:
        haystack = f"{row['name']} {row['description']} {row['owner']}".lower()
        if any(term in haystack for term in terms):
            ranked.append(row)
    return ranked or list(SERVICES)


def search_operational_incidents(service: str = "", status: str = "") -> list[dict]:
    rows = OPERATIONAL_INCIDENTS
    if service:
        rows = [row for row in rows if row["service"] == service]
    if status:
        rows = [row for row in rows if row["status"] == status]
    return rows


def known_service(text: str) -> str:
    lowered = text.lower().replace("_", "-")
    for service in SERVICES:
        name = service["name"]
        if name in lowered or name.replace("-", " ") in lowered:
            return name
    return ""


def _terms(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", query.lower()) if token not in _STOP and len(token) > 2]


def _overlap(terms: list[str], row: dict) -> int:
    haystack = " ".join(str(value).lower() for value in row.values())
    return sum(1 for term in terms if term in haystack)
