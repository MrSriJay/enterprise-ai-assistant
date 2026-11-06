"""Shared tool dispatch for the MCP server and the in-process fallback."""

from __future__ import annotations

from app.enterprise_data import (
    search_employees,
    search_operational_incidents,
    search_services,
)

TOOLS = {
    "search_employees",
    "search_services",
    "search_operational_incidents",
}


def dispatch_tool(name: str, arguments: dict) -> list[dict]:
    if name == "search_employees":
        return search_employees(str(arguments.get("query", "")))
    if name == "search_services":
        return search_services(str(arguments.get("query", "")))
    if name == "search_operational_incidents":
        return search_operational_incidents(
            str(arguments.get("service", "")),
            str(arguments.get("status", "")),
        )
    raise KeyError(name)
