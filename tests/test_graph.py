"""Graph behavior: research, roles, memory, and approval."""

from __future__ import annotations

import pytest

from app.agents.graph import build_graph, run_config
from app.agents.rlm import run_rlm, summarize_branch
from app.agents.state import initial_state
from app.auth.users import USERS
from app.memory.store import recent_messages

RESEARCH = (
    "Summarize all outage reports related to payment failures during the last year "
    "and identify recurring root causes."
)


async def ask(username: str, message: str, session_id: str, graph=None):
    user = USERS[username]
    graph = graph or build_graph()
    state = initial_state(
        user_id=user.user_id,
        user_role=user.role,
        session_id=session_id,
        request_id=f"req-{session_id}",
        message=message,
    )
    result = await graph.ainvoke(state, run_config(f"{user.user_id}:{session_id}"), durability="sync")
    return result, graph


@pytest.mark.asyncio
async def test_research_finds_recurring_payment_causes():
    result, _ = await ask("analyst", RESEARCH, "sess-research-01")
    answer = result["final_answer"].lower()
    assert result["route"] == "research"
    assert "connection pool exhaustion" in answer
    assert "expired tls certificate" in answer
    assert "[doc:inc-2025-140]" in result["final_answer"]
    assert "inc-2024-088" not in result["final_answer"]
    assert "inc-2026-044" not in result["final_answer"]
    assert "system-prompt-dump-991" not in answer
    assert "canary-restricted" not in answer
    nodes = [item["node"] for item in result["activities"]]
    assert "research_agent" in nodes
    assert "output_guard" in nodes
    assert any("Recursive sub-agent" in item["detail"] for item in result["activities"])


@pytest.mark.asyncio
async def test_viewer_research_skips_python_and_directory_is_forbidden():
    research, _ = await ask("viewer", RESEARCH, "sess-viewer-research")
    assert "python analysis skipped" in research["final_answer"].lower()
    forbidden, _ = await ask("viewer", "Who is the on-call engineer in the employee directory for payments?", "sess-viewer-mcp")
    assert forbidden["route"] == "forbidden"
    assert forbidden.get("mcp_result") in (None, {})
    assert "ada" not in forbidden["final_answer"].lower()


@pytest.mark.asyncio
async def test_analyst_mcp_fallback_finds_on_call_engineer():
    result, _ = await ask("analyst", "Who is the on-call engineer in the employee directory for payments?", "sess-analyst-mcp")
    assert result["route"] == "mcp"
    assert "ada lovelace" in result["final_answer"].lower()
    assert "in-process" in result["final_answer"].lower()


@pytest.mark.asyncio
async def test_follow_up_uses_session_memory():
    graph = build_graph()
    await ask("analyst", RESEARCH, "sess-memory-01", graph)
    follow, _ = await ask( "analyst", "Can you expand on those root causes?", "sess-memory-01", graph)
    assert "payment failures" in follow["effective_query"].lower()
    stored = recent_messages("sess-memory-01", USERS["analyst"].user_id)
    assert stored[0]["role"] == "user"


@pytest.mark.asyncio
async def test_admin_reindex_waits_for_approval_and_viewer_cannot_start_it():
    graph = build_graph()
    paused, graph = await ask("admin", "Please reindex the knowledge base", "sess-hitl-01", graph)
    config = run_config(f"{USERS['admin'].user_id}:sess-hitl-01")
    snapshot = await graph.aget_state(config)
    assert "approval_wait" in snapshot.next
    await graph.aupdate_state(config, {"approved": True})
    resumed = await graph.ainvoke(None, config, durability="sync")
    assert "rebuilt" in resumed["final_answer"].lower()

    denied, _ = await ask("viewer", "Please reindex the knowledge base", "sess-hitl-viewer")
    assert denied["route"] == "forbidden"
    assert "approval_wait" not in [item["node"] for item in denied["activities"]]


@pytest.mark.asyncio
async def test_failed_research_branch_does_not_drop_the_other_document():
    docs = [
        {"doc_id": "good-doc", "title": "Good outage", "created_date": "2026-01-01", "text": "The gateway recovered.", "root_cause": "disk"},
        {"doc_id": "bad-doc", "title": "Bad outage", "created_date": "2026-01-02", "text": "This branch explodes.", "root_cause": "disk", "force_fail": True},
    ]
    failures: list[str] = []

    async def record(detail: str, state_name: str = "research") -> None:
        return None

    summary = await summarize_branch(
        docs,
        "gateway",
        depth=0,
        max_depth=3,
        char_limit=10,
        failures=failures,
        record=record,
    )
    assert "good-doc" in summary
    assert failures
    assert "bad-doc" in failures[0]


@pytest.mark.asyncio
async def test_run_rlm_plan_excludes_the_old_incident():
    outcome = await run_rlm(RESEARCH, "analyst", {"thread_id": "unit"})
    ids = [doc["doc_id"] for doc in outcome["documents"]]
    assert "inc-2024-088" not in ids
    assert "inc-2026-058" in ids
    assert outcome["analysis"]["counts"]["connection pool exhaustion"] == 3
