"""HTTP surface: auth, a streamed chat, and session isolation."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.security.rate_limit import chat_limiter
from mcp_server.server import handle_rpc


def _events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def test_login_and_streamed_answer():
    with TestClient(create_app()) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["chunks"] > 0

        denied = client.post("/api/chat", json={"message": "hello", "session_id": "sess-no-auth"})
        assert denied.status_code == 401

        bad_login = client.post("/api/auth/login", json={"username": "viewer", "password": "nope"})
        assert bad_login.status_code == 401

        login = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
        token = login.json()["token"]
        response = client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "session_id": "sess-api-viewer",
                "message": "What does the certificate rotation runbook say about rollback?",
            },
        )
        assert response.status_code == 200
        events = _events(response.text)
        final = next(event for event in events if event["type"] == "final")
        assert "rb-cert-rotation" in final["answer"]
        assert any(event["type"] == "activity" for event in events)
        assert any(event["type"] == "token" for event in events)

        other = client.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
        stolen = client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {other.json()['token']}"},
            json={"session_id": "sess-api-viewer", "message": "hello"},
        )
        assert stolen.status_code == 403


def test_rate_limit_response(monkeypatch):
    limiter = chat_limiter()
    limiter.reset(capacity=1, refill_per_minute=0)
    try:
        with TestClient(create_app()) as client:
            login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
            headers = {"Authorization": f"Bearer {login.json()['token']}"}
            first = client.post("/api/chat", headers=headers, json={"session_id": "sess-rate-limit", "message": "help"})
            second = client.post("/api/chat", headers=headers, json={"session_id": "sess-rate-limit", "message": "help"})
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["error"] == "rate_limited"
    finally:
        limiter.reset(capacity=1000, refill_per_minute=1000)


def test_mcp_rpc_lists_and_calls_tools():
    listed = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "search_employees" in names
    called = handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search_services", "arguments": {"query": "settlement"}},
        }
    )
    data = json.loads(called["result"]["content"][0]["text"])
    assert any(row["name"] == "settlement-batch" for row in data)
