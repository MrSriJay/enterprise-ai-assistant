"""Role permissions for tools and document access.

Authorization is decided here, in ordinary Python, before a tool runs.
A model route that asks for a tool outside this table is rejected.
"""

from __future__ import annotations

ACCESS_LEVELS: dict[str, list[str]] = {
    "viewer": ["public", "internal"],
    "analyst": ["public", "internal", "confidential"],
    "administrator": ["public", "internal", "confidential", "restricted"],
}

TOOL_ROLES: dict[str, set[str]] = {
    "knowledge_search": {"viewer", "analyst", "administrator"},
    "python_analysis": {"analyst", "administrator"},
    "mcp_employee_directory": {"analyst", "administrator"},
    "mcp_service_catalog": {"analyst", "administrator"},
    "mcp_incident_records": {"analyst", "administrator"},
    "reindex": {"administrator"},
}

ROLE_ROUTES: dict[str, set[str]] = {
    "viewer": {"direct", "retrieve", "research", "blocked", "forbidden"},
    "analyst": {"direct", "retrieve", "research", "analytics", "mcp", "blocked", "forbidden"},
    "administrator": {
        "direct",
        "retrieve",
        "research",
        "analytics",
        "mcp",
        "admin_action",
        "blocked",
        "forbidden",
    },
}


def allowed_levels(role: str) -> list[str]:
    return list(ACCESS_LEVELS.get(role, ACCESS_LEVELS["viewer"]))


def tool_allowed(role: str, tool: str) -> bool:
    return role in TOOL_ROLES.get(tool, set())


def route_allowed(role: str, route: str) -> bool:
    return route in ROLE_ROUTES.get(role, set())
