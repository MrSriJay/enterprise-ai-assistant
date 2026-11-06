"""Minimal MCP server for dummy enterprise data.

The transport is JSON-RPC over HTTP with the method names used by MCP:
``initialize``, ``tools/list``, and ``tools/call``. It is intentionally small
so the agent integration can be read without a full streamable-HTTP session
manager. Run it beside the API, or let Docker Compose start it.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.tools.dispatch import TOOLS, dispatch_tool
from app.tools.mcp_client import validate_arguments

app = FastAPI(title="Harborline enterprise MCP", version="0.1.0")

_SCHEMAS = {
    "search_employees": {
        "name": "search_employees",
        "description": "Search the employee directory and on-call roster.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    "search_services": {
        "name": "search_services",
        "description": "Search the service catalog.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    },
    "search_operational_incidents": {
        "name": "search_operational_incidents",
        "description": "Read open or recent operational incident tickets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "status": {"type": "string"},
            },
        },
    },
}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "tools": sorted(TOOLS)}


@app.post("/mcp")
async def mcp(payload: dict) -> JSONResponse:
    return JSONResponse(handle_rpc(payload))


def handle_rpc(payload: dict) -> dict:
    method = payload.get("method")
    request_id = payload.get("id")
    if method == "initialize":
        return _ok(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "harborline-enterprise", "version": "0.1.0"},
            },
        )
    if method == "notifications/initialized":
        return _ok(request_id, {})
    if method == "tools/list":
        return _ok(request_id, {"tools": list(_SCHEMAS.values())})
    if method == "tools/call":
        params = payload.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOLS:
            return _error(request_id, -32602, "unknown tool")
        try:
            validated = validate_arguments(name, arguments)
            data = dispatch_tool(name, validated)
        except ValueError as exc:
            return _ok(
                request_id,
                {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            )
        return _ok(
            request_id,
            {"content": [{"type": "text", "text": json.dumps(data)}], "isError": False},
        )
    return _error(request_id, -32601, "method not found")


def _ok(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
