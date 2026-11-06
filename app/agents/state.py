"""Shared graph state.

Nodes return partial dictionaries. LangGraph replaces each key, so every node
that records an activity passes the full activity list forward. Per-turn fields
are cleared in ``input_guard`` so a previous retrieval cannot leak into the
next question on the same checkpoint thread.
"""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    user_id: str
    user_role: str
    session_id: str
    request_id: str
    thread_id: str
    user_message: str
    effective_query: str
    activities: list[dict]
    history: list[dict]
    memory_summary: str
    feedback_note: str
    intent: str
    route: str
    plan: dict
    retrieved: list[dict]
    analysis: dict | None
    mcp_result: dict | None
    research_summary: str
    draft_answer: str
    grounded_answer: str
    final_answer: str
    citations: list[dict]
    validation: dict
    degradation: list[str]
    error: str | None
    blocked_reason: str
    approved: bool
    hitl: dict | None


def conversation_thread(user_id: str, session_id: str) -> str:
    return f"{user_id}:{session_id}"


def initial_state(*, user_id: str, user_role: str, session_id: str, request_id: str, message: str) -> AgentState:
    return {
        "user_id": user_id,
        "user_role": user_role,
        "session_id": session_id,
        "request_id": request_id,
        "thread_id": conversation_thread(user_id, session_id),
        "user_message": message,
        "effective_query": message,
        "activities": [],
        "history": [],
        "memory_summary": "",
        "feedback_note": "",
        "intent": "",
        "route": "",
        "plan": {},
        "retrieved": [],
        "analysis": None,
        "mcp_result": None,
        "research_summary": "",
        "draft_answer": "",
        "grounded_answer": "",
        "final_answer": "",
        "citations": [],
        "validation": {},
        "degradation": [],
        "error": None,
        "blocked_reason": "",
        "approved": False,
        "hitl": None,
    }
