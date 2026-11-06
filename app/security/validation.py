"""Small validators shared by the API, MCP tools, and generated analysis code."""

from __future__ import annotations

import re


def require_text(value: object, *, field: str, max_len: int, pattern: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    if len(cleaned) > max_len:
        raise ValueError(f"{field} is too long")
    if not re.fullmatch(pattern, cleaned):
        raise ValueError(f"{field} contains unsupported characters")
    return cleaned


def is_iso_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
