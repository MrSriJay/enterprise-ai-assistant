"""Live activity events, a local trace file, and LangSmith setup.

Graph nodes publish here while they run. The API consumes the queue for the
active conversation thread, which avoids relying on ``contextvars`` propagation
across tasks on Python 3.10.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)
_QUEUES: dict[str, asyncio.Queue] = {}


def configure_tracing() -> None:
    """Export the env vars LangGraph and LangSmith already understand."""

    settings = get_settings()
    if not settings.langsmith_ready:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    logger.info(
        "LangSmith tracing enabled",
        extra={"fields": {"project": settings.langsmith_project}},
    )


def open_event_stream(thread_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _QUEUES[thread_id] = queue
    return queue


def close_event_stream(thread_id: str) -> None:
    _QUEUES.pop(thread_id, None)


async def publish(state: dict, event: dict) -> None:
    queue = _QUEUES.get(state.get("thread_id", ""))
    if queue is not None:
        await queue.put(event)
    settings = get_settings()
    if settings.local_trace and event.get("type") == "activity":
        await asyncio.to_thread(_append_trace, settings.trace_path, state, event)


def _append_trace(path, state: dict, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "thread_id": state.get("thread_id"),
        "request_id": state.get("request_id"),
        "event": event,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")


def make_activity(node: str, state_name: str, detail: str, **extra) -> dict:
    activity = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "node": node,
        "kind": state_name,
        "state": state_name,
        "detail": detail,
    }
    activity.update(extra)
    return activity


async def note(state: dict, node: str, state_name: str, detail: str, **extra) -> dict:
    activity = make_activity(node, state_name, detail, **extra)
    logger.info(detail, extra={"fields": {"node": node, "state": state_name, "thread_id": state.get("thread_id")}})
    await publish(state, {"type": "activity", "activity": activity})
    return activity


def with_activities(state: dict, events: list[dict], **updates) -> dict:
    updates["activities"] = [*state.get("activities", []), *events]
    return updates
