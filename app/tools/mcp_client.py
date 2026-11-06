"""MCP client used by the agent.

The client speaks a small JSON-RPC subset (initialize, tools/list, tools/call).
If the server cannot be reached and fallback is enabled, it calls the same
dispatch function the server uses and marks the result as degraded.
"""

from __future__ import annotations

import json
import re

import httpx

from app.config import get_settings
from app.enterprise_data import known_service
from app.logging_config import get_logger
from app.security.validation import require_text
from app.tools.dispatch import dispatch_tool

logger = get_logger(__name__)

_QUERY_PATTERN = r"[A-Za-z0-9 .,?'/:_-]+"


def plan_mcp_call(message: str) -> tuple[str, dict]:
    lowered = message.lower()
    if any(phrase in lowered for phrase in ["operational incident", "incident system", "open ticket", "ticket"]):
        status = "open" if "open" in lowered else ""
        return "search_operational_incidents", {"service": known_service(message), "status": status}
    if "service" in lowered or "catalog" in lowered:
        return "search_services", {"query": message[:180]}
    return "search_employees", {"query": message[:180]}


def validate_arguments(name: str, arguments: dict) -> dict:
    if name == "search_employees":
        return {"query": require_text(arguments.get("query", ""), field="query", max_len=180, pattern=_QUERY_PATTERN)}
    if name == "search_services":
        query = str(arguments.get("query", "")).strip()
        if not query:
            return {"query": ""}
        return {"query": require_text(query, field="query", max_len=180, pattern=_QUERY_PATTERN)}
    if name == "search_operational_incidents":
        service = str(arguments.get("service", "")).strip()
        status = str(arguments.get("status", "")).strip()
        if service and not re.fullmatch(r"[a-z0-9-]{2,40}", service):
            raise ValueError("service contains unsupported characters")
        if status and status not in {"open", "resolved"}:
            raise ValueError("status is invalid")
        return {"service": service, "status": status}
    raise ValueError("unknown tool")


async def call_mcp_tool(name: str, arguments: dict) -> dict:
    try:
        validated = validate_arguments(name, arguments)
    except ValueError as exc:
        return {
            "tool": name,
            "data": [],
            "error": "invalid_parameters",
            "detail": str(exc),
            "degraded": False,
            "source": "validation",
        }
    settings = get_settings()
    try:
        data = await _call_server(settings.mcp_url, name, validated, settings.mcp_timeout_seconds)
        return {"tool": name, "data": data, "degraded": False, "source": "mcp"}
    except Exception as exc:
        logger.warning(
            "MCP call failed",
            extra={"fields": {"tool": name, "error": type(exc).__name__}},
        )
        if not settings.mcp_fallback:
            return {
                "tool": name,
                "data": [],
                "error": "mcp_unavailable",
                "detail": type(exc).__name__,
                "degraded": True,
                "source": "mcp",
            }
        return {
            "tool": name,
            "data": dispatch_tool(name, validated),
            "degraded": True,
            "detail": type(exc).__name__,
            "source": "in-process",
        }


async def _call_server(url: str, name: str, arguments: dict, timeout: float) -> list[dict]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        await client.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "harborline-agent", "version": "0.1.0"},
                },
            },
        )
        response = await client.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        response.raise_for_status()
        payload = response.json()
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    result = payload.get("result") or {}
    if result.get("isError"):
        raise RuntimeError("tool returned isError")
    content = result.get("content") or []
    if not content:
        return []
    data = json.loads(content[0]["text"])
    if not isinstance(data, list):
        raise RuntimeError("tool payload was not a list")
    return data
