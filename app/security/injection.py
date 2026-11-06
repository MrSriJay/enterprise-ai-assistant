"""Detectors for instruction override, exfiltration, and tool-abuse text.

Document lines are scored only against the injection patterns. User messages
are also scored against bank-policy and privilege-escalation patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INJECTION_PATTERNS: list[tuple[str, str]] = [
    ("prompt_injection", r"ignore (all |any )?(previous|prior|above) (instructions|prompts|rules)"),
    ("prompt_injection", r"disregard (all |any )?(previous|prior|above) (instructions|prompts|rules)"),
    ("prompt_injection", r"you are now"),
    ("prompt_injection", r"(new|updated) instructions\s*:"),
    ("prompt_injection", r"reveal (the )?(system|developer|hidden) (prompt|message|instructions)"),
    ("prompt_injection", r"(print|dump|show) (the )?(system|developer) prompt"),
    ("prompt_injection", r"<\s*/?\s*(system|instructions)\s*>"),
    ("prompt_injection", r"\bjailbreak\b"),
    ("data_exfiltration", r"exfiltrate"),
    ("data_exfiltration", r"send (all |the )?(documents|secrets|context|customers) to"),
    ("tool_abuse", r"ignore (your |the )?(rbac|role|permissions|authorization)"),
    ("tool_abuse", r"override (the )?(role|permissions|authorization|guardrails?)"),
    ("tool_abuse", r"pretend (that )?i am (an? )?(admin|administrator)"),
    ("tool_abuse", r"bypass (the )?(rbac|authorization|guardrail|safety)"),
]

PROHIBITED_PATTERNS: list[tuple[str, str]] = [
    ("prohibited_request", r"\blaunder(?:ing)?\b"),
    ("prohibited_request", r"\b(carding|stolen cards?)\b"),
    ("prohibited_request", r"bypass (aml|kyc|fraud detection)"),
    ("prohibited_request", r"how to (steal|hack|phish)\b"),
]


@dataclass(frozen=True)
class Detection:
    blocked: bool
    category: str | None = None
    pattern: str | None = None


def screen_user_message(text: str) -> Detection:
    return _match(text, INJECTION_PATTERNS + PROHIBITED_PATTERNS)


def screen_untrusted_line(text: str) -> Detection:
    return _match(text, INJECTION_PATTERNS)


def sanitize_untrusted(text: str) -> tuple[str, int]:
    """Drop instruction-shaped lines found inside a document body."""

    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        if screen_untrusted_line(line).blocked:
            removed += 1
            kept.append("[removed untrusted instruction from source document]")
        else:
            kept.append(line)
    return "\n".join(kept).strip(), removed


def _match(text: str, patterns: list[tuple[str, str]]) -> Detection:
    haystack = text.lower()
    for category, pattern in patterns:
        if re.search(pattern, haystack):
            return Detection(True, category, pattern)
    return Detection(False)
