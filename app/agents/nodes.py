"""LangGraph nodes.

Each node owns one decision: screen, remember, route, retrieve, research,
call a tool, approve, phrase, validate, or save. Authorization is checked
again inside the tool nodes so a bad route cannot execute a tool by itself.
"""

from __future__ import annotations

import asyncio
import json

from langgraph.errors import GraphBubbleUp

from app.agents.llm import GROUNDED_SYSTEM, ROUTER_SYSTEM, complete, grounding_prompt
from app.agents.rlm import ANALYSIS_CODE, run_rlm
from app.agents.routing import contextualize, route_message
from app.agents.synthesize import answer_from_hits, render_mcp
from app.auth.rbac import ROLE_ROUTES, tool_allowed
from app.config import get_settings
from app.logging_config import get_logger
from app.memory.store import add_message, feedback_note, long_term_summary, recent_messages, remember
from app.observability import note, with_activities
from app.retrieval.service import rebuild_index, search_knowledge
from app.security.guardrails import validate_answer
from app.security.injection import screen_user_message
from app.tools.mcp_client import call_mcp_tool, plan_mcp_call
from app.tools.sandbox import SandboxError, execute

logger = get_logger(__name__)

REFUSALS = {
    "prompt_injection": "I can't follow instructions that try to override the assistant's rules.",
    "data_exfiltration": "I can't help move internal documents or secrets out of the bank's controls.",
    "tool_abuse": "I can't change your role or bypass authorization for a tool.",
    "prohibited_request": "I can't help with requests that would abuse Harborline Commercial Bank's systems or customers.",
}


def safe_node(node_name: str):
    def decorator(func):
        async def wrapper(state: dict) -> dict:
            try:
                return await func(state)
            except GraphBubbleUp:
                raise
            except Exception as exc:
                logger.exception("Node failed", extra={"fields": {"node": node_name}})
                event = await note(
                    state,
                    node_name,
                    "error",
                    f"{node_name} failed ({type(exc).__name__}). Later nodes will answer with what they still have.",
                )
                degradation = [*state.get("degradation", []), f"{node_name} failed"]
                return with_activities(state, [event], degradation=degradation, error=type(exc).__name__)

        return wrapper

    return decorator


@safe_node("input_guard")
async def input_guard(state: dict) -> dict:
    started = await note(state, "input_guard", "validating", "Checking the request for injection, tool abuse, and prohibited asks.")
    detection = screen_user_message(state.get("user_message") or "")
    events = [started]
    cleared = {
        "retrieved": [],
        "research_summary": "",
        "grounded_answer": "",
        "draft_answer": "",
        "final_answer": "",
        "citations": [],
        "analysis": None,
        "mcp_result": None,
        "validation": {},
        "degradation": [],
        "error": None,
        "approved": False,
        "hitl": None,
        "plan": {},
        "blocked_reason": "",
        "intent": "",
        "route": "",
    }
    if detection.blocked:
        refusal = REFUSALS.get(detection.category or "", REFUSALS["prompt_injection"])
        events.append(
            await note(state, "input_guard", "validation", f"Blocked the message ({detection.category}).")
        )
        cleared.update(
            route="blocked",
            intent="blocked",
            blocked_reason=detection.category or "prompt_injection",
            draft_answer=refusal,
        )
    else:
        events.append(await note(state, "input_guard", "validation", "Input accepted."))
    fresh = with_activities(state, events, **cleared)
    # Start each turn with a clean activity trace. Older turns stay in session memory.
    fresh["activities"] = events
    return fresh


@safe_node("memory_load")
async def memory_load(state: dict) -> dict:
    history = await asyncio.to_thread(recent_messages, state["session_id"], state["user_id"])
    summary = await asyncio.to_thread(long_term_summary, state["user_id"])
    steer = await asyncio.to_thread(feedback_note, state["user_id"])
    if state.get("route") == "blocked":
        effective = state["user_message"]
    else:
        effective = contextualize(state["user_message"], history)
    long_term_lines = len([line for line in summary.splitlines() if line.strip()])
    event = await note(
        state,
        "memory_load",
        "memory",
        f"Loaded {len(history)} earlier turns and {long_term_lines} long-term notes.",
    )
    return with_activities(
        state,
        [event],
        history=history,
        memory_summary=summary,
        feedback_note=steer,
        effective_query=effective,
    )


@safe_node("supervisor")
async def supervisor(state: dict) -> dict:
    if state.get("route") == "blocked":
        event = await note(state, "supervisor", "routing", "Input was blocked, so no tool route was chosen.")
        return with_activities(state, [event])
    decision = route_message(state.get("effective_query") or state["user_message"], state["user_role"])
    events = [
        await note(
            state,
            "supervisor",
            "routing",
            f"intent={decision.intent} route={decision.route}. {decision.reason}",
        )
    ]
    suggestion = await _model_suggestion(state, decision.route)
    if suggestion is not None:
        events.append(suggestion)
    updates = {"intent": decision.intent, "route": decision.route, "plan": {"reason": decision.reason}}
    if decision.reply:
        updates["draft_answer"] = decision.reply
    return with_activities(state, events, **updates)


@safe_node("retrieval_agent")
async def retrieval_agent(state: dict) -> dict:
    if not tool_allowed(state["user_role"], "knowledge_search"):
        event = await note(state, "retrieval_agent", "validation", "Knowledge search is not allowed for this role.")
        return with_activities(
            state,
            [event],
            route="forbidden",
            draft_answer="Knowledge search is not allowed for this role.",
        )
    started = await note(state, "retrieval_agent", "retrieval", "Running hybrid search across allowed namespaces.")
    result = await search_knowledge(state.get("effective_query") or state["user_message"], role=state["user_role"])
    hits = result["hits"]
    finished = await note(state, "retrieval_agent", "retrieval", f"Hybrid search returned {len(hits)} chunks.")
    degradation = [*state.get("degradation", []), *result.get("degradation", [])]
    return with_activities(state, [started, finished], retrieved=hits, degradation=degradation)


@safe_node("research_agent")
async def research_agent(state: dict) -> dict:
    if not tool_allowed(state["user_role"], "knowledge_search"):
        event = await note(state, "research_agent", "validation", "Research is not allowed for this role.")
        return with_activities(state, [event], route="forbidden", draft_answer="Research is not allowed for this role.")
    outcome = await run_rlm(state.get("effective_query") or state["user_message"], state["user_role"], state)
    degradation = list(state.get("degradation") or [])
    if outcome["failures"]:
        degradation.append("one or more research branches failed")
    return with_activities(
        state,
        outcome["activities"],
        retrieved=outcome["documents"],
        research_summary=outcome["summary"],
        analysis=outcome["analysis"],
        plan=outcome["plan"],
        degradation=degradation,
    )


@safe_node("analysis_agent")
async def analysis_agent(state: dict) -> dict:
    if not tool_allowed(state["user_role"], "python_analysis"):
        event = await note(state, "analysis_agent", "validation", "Python analysis is not allowed for this role.")
        return with_activities(
            state,
            [event],
            route="forbidden",
            draft_answer="The analytics tool is limited to analysts and administrators.",
        )
    started = await note(state, "analysis_agent", "tool", "Running the Python analysis tool on the retrieved documents.")
    unique: dict[str, dict] = {}
    for hit in state.get("retrieved") or []:
        unique.setdefault(hit["doc_id"], hit)
    slim = [
        {"doc_id": doc["doc_id"], "root_cause": doc.get("root_cause") or "", "title": doc.get("title", "")}
        for doc in unique.values()
    ]
    try:
        analysis = await asyncio.wait_for(
            asyncio.to_thread(execute, ANALYSIS_CODE, docs=slim),
            timeout=get_settings().tool_timeout_seconds,
        )
    except (SandboxError, TimeoutError) as exc:
        event = await note(state, "analysis_agent", "error", f"Analysis tool failed ({type(exc).__name__}).")
        degradation = [*state.get("degradation", []), "python analysis failed"]
        return with_activities(state, [started, event], degradation=degradation)
    finished = await note(state, "analysis_agent", "tool", f"Analysis counts: {analysis.get('counts')}")
    return with_activities(state, [started, finished], analysis=analysis)


@safe_node("mcp_agent")
async def mcp_agent(state: dict) -> dict:
    tool_name, arguments = plan_mcp_call(state.get("effective_query") or state["user_message"])
    permission = {
        "search_employees": "mcp_employee_directory",
        "search_services": "mcp_service_catalog",
        "search_operational_incidents": "mcp_incident_records",
    }[tool_name]
    if not tool_allowed(state["user_role"], permission):
        event = await note(state, "mcp_agent", "validation", f"{tool_name} is not allowed for this role.")
        return with_activities(
            state,
            [event],
            route="forbidden",
            draft_answer="That enterprise tool is outside your role.",
        )
    started = await note(state, "mcp_agent", "tool", f"Calling MCP tool {tool_name}.")
    try:
        result = await asyncio.wait_for(
            call_mcp_tool(tool_name, arguments),
            timeout=get_settings().tool_timeout_seconds,
        )
    except TimeoutError:
        result = {"tool": tool_name, "data": [], "error": "mcp_unavailable", "degraded": True, "source": "timeout"}
    finished = await note(
        state,
        "mcp_agent",
        "tool",
        f"MCP tool {tool_name} finished from {result.get('source')} (degraded={result.get('degraded')}).",
    )
    degradation = list(state.get("degradation") or [])
    if result.get("degraded"):
        degradation.append("MCP server unavailable")
    return with_activities(state, [started, finished], mcp_result=result, degradation=degradation)


@safe_node("approval_request")
async def approval_request(state: dict) -> dict:
    if not tool_allowed(state["user_role"], "reindex"):
        event = await note(state, "approval_request", "validation", "Reindex was refused before approval.")
        return with_activities(
            state,
            [event],
            route="forbidden",
            draft_answer="Rebuilding the index is limited to administrators.",
        )
    payload = {
        "action": "reindex",
        "reason": "Rebuilding the knowledge index rewrites embeddings and namespaces. An administrator has to approve it.",
    }
    event = await note(state, "approval_request", "approval", "Waiting for an administrator to approve the reindex.")
    return with_activities(state, [event], hitl=payload, draft_answer=payload["reason"])


@safe_node("approval_wait")
async def approval_wait(state: dict) -> dict:
    # The graph pauses before this node (interrupt_before). Resume writes
    # ``approved`` into the checkpoint, then this node observes that decision.
    # Calling LangGraph's interrupt() here is unreliable on Python 3.10 because
    # the node task does not keep the runnable config context.
    if state.get("approved"):
        event = await note(state, "approval_wait", "approval", "Administrator approved the reindex.")
        return with_activities(state, [event], approved=True)
    event = await note(state, "approval_wait", "approval", "Administrator rejected the reindex.")
    return with_activities(
        state,
        [event],
        approved=False,
        route="forbidden",
        draft_answer="The reindex was not approved, so the index was left unchanged.",
    )


@safe_node("admin_action")
async def admin_action(state: dict) -> dict:
    if not state.get("approved") or not tool_allowed(state["user_role"], "reindex"):
        event = await note(state, "admin_action", "validation", "Reindex did not run because it was not approved.")
        return with_activities(
            state,
            [event],
            draft_answer="The reindex did not run.",
            route="forbidden",
        )
    started = await note(state, "admin_action", "tool", "Rebuilding the knowledge index.")
    try:
        count = await asyncio.wait_for(
            asyncio.to_thread(rebuild_index),
            timeout=max(get_settings().tool_timeout_seconds, 30),
        )
    except TimeoutError:
        event = await note(state, "admin_action", "error", "Reindex timed out. The previous index is still being served.")
        degradation = [*state.get("degradation", []), "reindex timed out"]
        return with_activities(
            state,
            [started, event],
            degradation=degradation,
            draft_answer="Reindex timed out. The previous index is still being served.",
        )
    except Exception as exc:
        event = await note(state, "admin_action", "error", f"Reindex failed ({type(exc).__name__}). The previous index is still being served.")
        degradation = [*state.get("degradation", []), "reindex failed"]
        return with_activities(
            state,
            [started, event],
            degradation=degradation,
            draft_answer="Reindex failed. The previous index is still being served.",
        )
    finished = await note(state, "admin_action", "tool", f"Index rebuilt with {count} chunks.")
    return with_activities(
        state,
        [started, finished],
        draft_answer=f"The knowledge index was rebuilt with {count} chunks.",
    )


@safe_node("response_agent")
async def response_agent(state: dict) -> dict:
    route = state.get("route") or ""
    events: list[dict] = []
    preset = {"blocked", "forbidden", "direct", "admin_action"}
    if route in preset and state.get("draft_answer"):
        events.append(await note(state, "response_agent", "responding", "Using the prepared response without a model call."))
        return with_activities(
            state,
            events,
            grounded_answer=state["draft_answer"],
            draft_answer=state["draft_answer"],
        )

    if route == "mcp":
        grounded = render_mcp(state.get("mcp_result"))
    elif state.get("research_summary"):
        grounded = state["research_summary"]
    else:
        grounded = _analytics_prefix(state) + answer_from_hits(
            state.get("effective_query") or state["user_message"],
            state.get("retrieved") or [],
        )
        grounded = grounded.strip()
        if not grounded:
            if state.get("degradation"):
                grounded = "I couldn't complete the document search. " + " ".join(state["degradation"])
            else:
                grounded = (
                    "I couldn't find enough evidence in the documents your role is allowed to read. I won't guess."
                )

    draft = grounded
    degradation = list(state.get("degradation") or [])
    if get_settings().llm_ready and route in {"retrieve", "research", "analytics", "mcp"}:
        events.append(await note(state, "response_agent", "generating", "Asking the model to phrase the grounded draft."))
        polished = await complete(GROUNDED_SYSTEM, grounding_prompt(state, grounded))
        if polished:
            draft = polished
        else:
            degradation.append("language model unavailable; returned the grounded draft")
            events.append(
                await note(state, "response_agent", "error", "Model call failed. Keeping the grounded draft.")
            )
    else:
        events.append(await note(state, "response_agent", "responding", "Composed a grounded answer without a model call."))
    return with_activities(state, events, draft_answer=draft, grounded_answer=grounded, degradation=degradation)


@safe_node("output_guard")
async def output_guard(state: dict) -> dict:
    report = validate_answer(
        state.get("draft_answer") or "",
        route=state.get("route") or "",
        retrieved=state.get("retrieved") or [],
        grounded_answer=state.get("grounded_answer") or "",
    )
    detail = "Validation passed." if report["status"] == "passed" else "Validation repaired the answer: " + "; ".join(report["issues"])
    event = await note(state, "output_guard", "validation", detail)
    return with_activities(
        state,
        [event],
        final_answer=report["answer"],
        citations=report["citations"],
        validation={key: value for key, value in report.items() if key != "answer"},
    )


@safe_node("memory_save")
async def memory_save(state: dict) -> dict:
    user_text = "[blocked message]" if state.get("route") == "blocked" else state.get("user_message", "")
    answer = state.get("final_answer") or ""
    await asyncio.to_thread(add_message, state["session_id"], state["user_id"], "user", user_text)
    await asyncio.to_thread(add_message, state["session_id"], state["user_id"], "assistant", answer)
    if state.get("route") != "blocked":
        cited = ", ".join(item["doc_id"] for item in state.get("citations") or []) or "none"
        await asyncio.to_thread(remember, state["user_id"], f"Q: {user_text[:160]} Docs: {cited}")
    event = await note(state, "memory_save", "memory", "Saved the turn to session memory and the long-term summary.")
    return with_activities(state, [event])


def route_after_supervisor(state: dict) -> str:
    route = state.get("route")
    if route in {"retrieve", "analytics"}:
        return "retrieval_agent"
    if route == "research":
        return "research_agent"
    if route == "mcp":
        return "mcp_agent"
    if route == "admin_action":
        return "approval_request"
    return "response_agent"


def route_after_retrieval(state: dict) -> str:
    if state.get("route") == "analytics" and tool_allowed(state.get("user_role", ""), "python_analysis"):
        return "analysis_agent"
    return "response_agent"


def route_after_approval_request(state: dict) -> str:
    if state.get("route") == "forbidden":
        return "response_agent"
    return "approval_wait"


def route_after_approval(state: dict) -> str:
    if state.get("approved"):
        return "admin_action"
    return "response_agent"


async def _model_suggestion(state: dict, policy_route: str):
    if not get_settings().llm_ready:
        return None
    raw = await complete(
        ROUTER_SYSTEM,
        json.dumps({"role": state["user_role"], "query": state.get("effective_query") or state["user_message"]}),
        json_mode=True,
    )
    if not raw:
        return await note(state, "supervisor", "routing", "Model suggestion was unavailable. The policy route stands.")
    try:
        suggested = json.loads(raw).get("route")
    except json.JSONDecodeError:
        return await note(state, "supervisor", "validation", "Model suggestion was not valid JSON. The policy route stands.")
    allowed = ROLE_ROUTES.get(state["user_role"], set())
    if suggested not in allowed:
        return await note(
            state,
            "supervisor",
            "validation",
            f"Rejected model route '{suggested}' because this role cannot use it.",
        )
    return await note(
        state,
        "supervisor",
        "routing",
        f"Model suggested '{suggested}'. Policy route '{policy_route}' remains in force.",
    )


def _analytics_prefix(state: dict) -> str:
    analysis = state.get("analysis") or {}
    counts = analysis.get("counts") or {}
    if not counts:
        return ""
    lines = ["Python analysis of the retrieved documents:"]
    for cause, count in sorted(counts.items(), key=lambda item: (-item[1], str(item[0]))):
        lines.append(f"- {cause}: {count}")
    recurring = analysis.get("recurring") or []
    if recurring:
        lines.append("Recurring root causes: " + ", ".join(str(item) for item in recurring) + ".")
    lines.append("")
    return "\n".join(lines)
