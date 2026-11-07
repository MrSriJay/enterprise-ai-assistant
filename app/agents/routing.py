"""Policy router.

The supervisor asks this module where to go before it trusts a model.
Specialized and privileged routes are decided with explicit rules so a prompt
cannot talk the assistant into a tool the role does not have.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.rbac import route_allowed

DIRECT_REPLY = (
    "I am the Enterprise AI Assistant. "
    "Ask me about policies, runbooks, architecture, incidents, or product specifications. "
    "Analysts and administrators can also use the employee directory, the service catalog, "
    "operational incident tickets, and the analytics tool."
)

FORBIDDEN_REPLY = (
    "Your role can chat and search the documents it is cleared to read. "
    "That tool is outside your permissions, and I will not run it."
)


@dataclass(frozen=True)
class Decision:
    intent: str
    route: str
    reason: str
    reply: str = ""


def route_message(query: str, role: str) -> Decision:
    text = " ".join(query.lower().split())
    if _is_greeting(text):
        return Decision("greeting", "direct", "Greeting or help request.", DIRECT_REPLY)
    if any(phrase in text for phrase in ("reindex", "rebuild the index", "rebuild index")):
        if route_allowed(role, "admin_action"):
            return Decision("admin", "admin_action", "The user asked to rebuild the knowledge index.")
        return Decision("unauthorized_tool", "forbidden", "Reindex is limited to administrators.", FORBIDDEN_REPLY)
    if any(phrase in text for phrase in ("python tool", "analytics tool", "group by")):
        if role == "viewer":
            return Decision(
                "unauthorized_tool",
                "forbidden",
                "Analytics tools are not available to viewers.",
                FORBIDDEN_REPLY,
            )
        return Decision("analytics", "analytics", "The user asked for a structured calculation.")
    if _wants_mcp(text):
        if route_allowed(role, "mcp"):
            return Decision("enterprise_lookup", "mcp", "The question targets an enterprise system, not the document index.")
        return Decision(
            "unauthorized_tool",
            "forbidden",
            "Directory and catalog tools are not available to viewers.",
            FORBIDDEN_REPLY,
        )
    if _is_broad(text):
        return Decision("research", "research", "The question needs a filtered, batched look across the collection.")
    return Decision("knowledge", "retrieve", "The question can be answered from a targeted document search.")


def contextualize(message: str, history: list[dict]) -> str:
    """Fold a short follow-up into the previous user question when it is referential."""

    if not history:
        return message
    lowered = message.lower()
    referential = any(
        phrase in lowered
        for phrase in ("those", "that incident", "the same", "more detail", "what about", "expand on", "tell me more")
    )
    if not referential:
        return message
    previous = [item["content"] for item in history if item.get("role") == "user" and item.get("content")]
    if not previous:
        return message
    return f"{previous[-1]}\nFollow-up: {message}"


def _is_greeting(text: str) -> bool:
    if any(keyword in text for keyword in ("runbook", "policy", "incident", "payment", "outage", "reindex")):
        return False
    greetings = ("hi", "hello", "hey", "help", "good morning", "good afternoon", "what can you do")
    return any(text == greeting or text.startswith(greeting + " ") for greeting in greetings) and len(text) < 80


def _wants_mcp(text: str) -> bool:
    phrases = (
        "employee directory",
        "who is",
        "who's",
        "on-call",
        "on call",
        "service catalog",
        "service owner",
        "lookup employee",
        "staff directory",
        "operational incident",
        "incident system",
        "open ticket",
    )
    if any(phrase in text for phrase in phrases):
        return True
    return "catalog" in text and "service" in text


def _is_broad(text: str) -> bool:
    phrases = (
        "summarize all",
        "summarize the outage",
        "summarize the incident",
        "summarize every",
        "summary of all",
        "all outage",
        "all incident",
        "recurring",
        "root cause",
        "last year",
        "past year",
        "over the last",
        "common cause",
        "keeps happening",
    )
    return any(phrase in text for phrase in phrases)
