"""Chat window plus a live view of the LangGraph run."""

from __future__ import annotations

import json
import os
import uuid

import httpx
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="Harborline Assistant", layout="wide")


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


def _ensure_session() -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_hitl" not in st.session_state:
        st.session_state.pending_hitl = None


def _login(username: str, password: str) -> None:
    response = httpx.post(
        f"{API_BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=20,
    )
    if response.status_code != 200:
        st.session_state.login_error = response.json().get("message", "Login failed.")
        return
    payload = response.json()
    st.session_state.token = payload["token"]
    st.session_state.role = payload["role"]
    st.session_state.display_name = payload["display_name"]
    st.session_state.login_error = ""


def _stream(payload: dict, activity_box, answer_box) -> dict | None:
    activities: list[dict] = []
    answer = ""
    final = None
    with httpx.stream(
        "POST",
        f"{API_BASE_URL}/api/chat",
        headers=_auth_headers(),
        json=payload,
        timeout=120,
    ) as response:
        if response.status_code != 200:
            detail = response.read().decode("utf-8", errors="replace")
            answer_box.error(detail)
            return None
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            if event["type"] == "activity":
                activities.append(event["activity"])
                _render_activity(activity_box, activities)
            elif event["type"] == "token":
                answer += event.get("text", "")
                answer_box.markdown(answer)
            elif event["type"] == "hitl":
                st.session_state.pending_hitl = event.get("payload")
            elif event["type"] == "final":
                final = event
                answer = event.get("answer") or answer
                activities = event.get("activities") or activities
                answer_box.markdown(answer)
                _render_activity(activity_box, activities)
            elif event["type"] == "error":
                answer_box.error(event.get("message", "The request failed."))
    if final is None:
        return None
    final["answer"] = answer
    final["activities"] = activities
    return final


def _render_activity(box, activities: list[dict]) -> None:
    with box.container():
        if not activities:
            st.caption("Idle")
            return
        latest = activities[-1]
        left, right = st.columns(2)
        left.metric("Active node", latest.get("node", "idle"))
        right.metric("Agent state", latest.get("state", "idle"))
        for activity in activities:
            st.markdown(f"**{activity.get('node')}** · `{activity.get('state')}`")
            st.caption(activity.get("detail", ""))


def _send(message: str | None, resume: dict | None, activity_box, answer_box) -> None:
    payload: dict = {"session_id": st.session_state.session_id}
    if resume is not None:
        payload["resume"] = resume
    else:
        payload["message"] = message or ""
        st.session_state.messages.append({"role": "user", "content": message})
    result = _stream(payload, activity_box, answer_box)
    if result is None:
        return
    if result.get("pending_approval"):
        st.session_state.pending_hitl = result.get("hitl") or {"action": "reindex"}
    else:
        st.session_state.pending_hitl = None
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result.get("answer", ""),
            "citations": result.get("citations") or [],
            "validation": result.get("validation") or {},
            "degradation": result.get("degradation") or [],
            "activities": result.get("activities") or [],
            "route": result.get("route"),
        }
    )


_ensure_session()
st.title("Harborline Commercial Bank")
st.caption("Internal assistant. The panel on the right is the live LangGraph trace for this turn.")

with st.sidebar:
    st.subheader("Sign in")
    if "token" not in st.session_state:
        username = st.text_input("Username", value="analyst")
        password = st.text_input("Password", value="analyst123", type="password")
        st.caption("Demo users: viewer / viewer123, analyst / analyst123, admin / admin123")
        if st.button("Login", type="primary"):
            _login(username, password)
            st.rerun()
        if st.session_state.get("login_error"):
            st.error(st.session_state.login_error)
        st.stop()
    st.write(f"{st.session_state.display_name} · `{st.session_state.role}`")
    if st.button("Log out"):
        for key in ("token", "role", "display_name", "messages", "pending_hitl"):
            st.session_state.pop(key, None)
        st.rerun()
    try:
        health = httpx.get(f"{API_BASE_URL}/api/health", timeout=5).json()
        st.caption(
            f"Model: {health.get('chat_model')} · chunks: {health.get('chunks')} · "
            f"LangSmith: {health.get('langsmith')}"
        )
    except httpx.HTTPError:
        st.warning("API is not reachable.")

chat_col, activity_col = st.columns([3, 2])
activity_box = activity_col.container()
with activity_col:
    st.subheader("Agent activity")

with chat_col:
    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                validation = message.get("validation") or {}
                if validation:
                    st.caption(f"Validation: {validation.get('status', 'n/a')}")
                for item in message.get("degradation") or []:
                    st.warning(item)
                citations = message.get("citations") or []
                if citations:
                    with st.expander("Evidence"):
                        for citation in citations:
                            st.markdown(
                                f"**{citation['title']}** `{citation['doc_id']}` · "
                                f"{citation['document_type']} · {citation['access_level']} · {citation['created_date']}"
                            )
                            st.caption(citation.get("snippet", ""))
                if message.get("activities"):
                    with st.expander("Trace for this answer"):
                        for activity in message["activities"]:
                            st.markdown(f"**{activity['node']}** · `{activity['state']}`")
                            st.caption(activity["detail"])
                helpful, poor = st.columns(2)
                if helpful.button("Helpful", key=f"up-{index}"):
                    httpx.post(
                        f"{API_BASE_URL}/api/feedback",
                        headers=_auth_headers(),
                        json={"session_id": st.session_state.session_id, "rating": 5, "comment": "helpful"},
                        timeout=10,
                    )
                    st.toast("Thanks. That rating is stored for the next turn.")
                if poor.button("Not helpful", key=f"down-{index}"):
                    httpx.post(
                        f"{API_BASE_URL}/api/feedback",
                        headers=_auth_headers(),
                        json={"session_id": st.session_state.session_id, "rating": 1, "comment": "not helpful"},
                        timeout=10,
                    )
                    st.toast("Recorded. The next answer will be steered to be shorter and more cited.")

    if st.session_state.pending_hitl:
        st.warning(st.session_state.pending_hitl.get("reason", "Approval required."))
        approve, reject = st.columns(2)
        if approve.button("Approve reindex", type="primary"):
            _send(None, {"approved": True}, activity_box, st.empty())
            st.rerun()
        if reject.button("Reject"):
            _send(None, {"approved": False}, activity_box, st.empty())
            st.rerun()

    prompt = st.chat_input("Ask about policies, incidents, the directory, or a reindex")
    if prompt:
        with chat_col:
            answer_box = st.empty()
        _send(prompt, None, activity_box, answer_box)
        st.rerun()
