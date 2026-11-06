"""Compile the assistant graph.

The checkpointer lets a run pause before ``approval_wait``. The API updates
``approved`` on that checkpoint and invokes the graph again with no new input,
which is the human-in-the-loop step. Tests build their own graph so cases do
not share checkpoints. The API keeps one compiled graph for the process.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    admin_action,
    analysis_agent,
    approval_request,
    approval_wait,
    input_guard,
    mcp_agent,
    memory_load,
    memory_save,
    output_guard,
    research_agent,
    response_agent,
    retrieval_agent,
    route_after_approval,
    route_after_approval_request,
    route_after_retrieval,
    route_after_supervisor,
    supervisor,
)
from app.agents.state import AgentState

_GRAPH = None


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("input_guard", input_guard)
    graph.add_node("memory_load", memory_load)
    graph.add_node("supervisor", supervisor)
    graph.add_node("retrieval_agent", retrieval_agent)
    graph.add_node("research_agent", research_agent)
    graph.add_node("analysis_agent", analysis_agent)
    graph.add_node("mcp_agent", mcp_agent)
    graph.add_node("approval_request", approval_request)
    graph.add_node("approval_wait", approval_wait)
    graph.add_node("admin_action", admin_action)
    graph.add_node("response_agent", response_agent)
    graph.add_node("output_guard", output_guard)
    graph.add_node("memory_save", memory_save)

    graph.add_edge(START, "input_guard")
    graph.add_edge("input_guard", "memory_load")
    graph.add_edge("memory_load", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "retrieval_agent": "retrieval_agent",
            "research_agent": "research_agent",
            "mcp_agent": "mcp_agent",
            "approval_request": "approval_request",
            "response_agent": "response_agent",
        },
    )
    graph.add_conditional_edges(
        "retrieval_agent",
        route_after_retrieval,
        {"analysis_agent": "analysis_agent", "response_agent": "response_agent"},
    )
    graph.add_edge("research_agent", "response_agent")
    graph.add_edge("analysis_agent", "response_agent")
    graph.add_edge("mcp_agent", "response_agent")
    graph.add_conditional_edges(
        "approval_request",
        route_after_approval_request,
        {"approval_wait": "approval_wait", "response_agent": "response_agent"},
    )
    graph.add_conditional_edges(
        "approval_wait",
        route_after_approval,
        {"admin_action": "admin_action", "response_agent": "response_agent"},
    )
    graph.add_edge("admin_action", "response_agent")
    graph.add_edge("response_agent", "output_guard")
    graph.add_edge("output_guard", "memory_save")
    graph.add_edge("memory_save", END)
    return graph.compile(checkpointer=InMemorySaver(), interrupt_before=["approval_wait"])


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
