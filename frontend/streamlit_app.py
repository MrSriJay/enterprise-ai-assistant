"""Chat window plus a live view of the LangGraph run."""

from __future__ import annotations

import json
import os
import uuid

import httpx
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

STARTERS = {
    "viewer": {
        ":material/vpn_key: Certificate rollback": "What does the certificate rotation runbook say about rollback?",
        ":material/help: What can you do?": "What can you do?",
    },
    "analyst": {
        ":material/warning: Payment outages": "Summarize all outage reports related to payment failures during the last year and identify recurring root causes.",
        ":material/badge: On-call engineer": "Who is the on-call engineer in the employee directory for payments?",
        ":material/vpn_key: Certificate rollback": "What does the certificate rotation runbook say about rollback?",
    },
    "administrator": {
        ":material/database: Reindex": "Please reindex the knowledge base.",
        ":material/badge: On-call engineer": "Who is the on-call engineer in the employee directory for payments?",
        ":material/vpn_key: Certificate rollback": "What does the certificate rotation runbook say about rollback?",
    },
}

NODE_ICONS = {
    "input_guard": ":material/shield:",
    "memory_load": ":material/history:",
    "memory_save": ":material/save:",
    "supervisor": ":material/account_tree:",
    "retrieval_agent": ":material/search:",
    "research_agent": ":material/travel_explore:",
    "analysis_agent": ":material/query_stats:",
    "mcp_agent": ":material/dns:",
    "approval_request": ":material/approval:",
    "approval_wait": ":material/hourglass_top:",
    "admin_action": ":material/database:",
    "response_agent": ":material/chat:",
    "output_guard": ":material/verified:",
}

ROLE_ICONS = {
    "viewer": ":material/visibility:",
    "analyst": ":material/query_stats:",
    "administrator": ":material/admin_panel_settings:",
}

ROLE_COLORS = {"viewer": "gray", "analyst": "blue", "administrator": "green"}
AVATARS = {"user": ":material/person:", "assistant": ":material/support_agent:"}

st.set_page_config(
    page_title="Enterprise AI Assistant",
    page_icon=":material/support_agent:",
    layout="wide",
)


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
    try:
        response = httpx.post(
            f"{API_BASE_URL}/api/auth/login",
            json={"username": username, "password": password},
            timeout=20,
        )
    except httpx.HTTPError:
        st.session_state.login_error = "The API is not running. Start it on port 8000, then sign in again."
        return
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
    thinking = True
    answer_box.markdown(":shimmer[thinking...]")
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
                thinking = False
                answer += event.get("text", "")
                answer_box.markdown(answer)
            elif event["type"] == "hitl":
                st.session_state.pending_hitl = event.get("payload")
            elif event["type"] == "final":
                thinking = False
                final = event
                answer = event.get("answer") or answer
                activities = event.get("activities") or activities
                answer_box.markdown(answer)
                _render_activity(activity_box, activities)
            elif event["type"] == "error":
                thinking = False
                answer_box.error(event.get("message", "The request failed."))
    if thinking:
        answer_box.markdown(":shimmer[thinking...]")
    if final is None:
        return None
    final["answer"] = answer
    final["activities"] = activities
    return final


def _render_activity(slot, activities: list[dict]) -> None:
    with slot.container(border=True):
        if not activities:
            st.caption(":material/pending: Ask a question to see each agent step here.")
            return
        for activity in activities:
            node = activity.get("node") or "idle"
            icon = NODE_ICONS.get(node, ":material/radio_button_checked:")
            state = str(activity.get("state") or "running")
            current = activity is activities[-1]
            if current:
                st.markdown(f"{icon} **{node}**")
                st.badge(state, color="blue", icon=":material/bolt:")
            else:
                st.markdown(f"{icon} `{node}` · {state}")
            st.caption(activity.get("detail") or "")


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


def _validation_badge(validation: dict) -> None:
    status = str(validation.get("status") or "")
    if not status:
        return
    if status == "passed":
        color = "green"
    elif status == "pending_approval":
        color = "orange"
    else:
        color = "red"
    st.badge(status.replace("_", " "), color=color, icon=":material/verified:")


_ensure_session()

with st.sidebar:
    st.markdown("### :material/account_circle: Account")
    if "token" not in st.session_state:
        username = st.text_input("Username", value="analyst")
        password = st.text_input("Password", value="analyst123", type="password")
        st.caption("viewer / viewer123 · analyst / analyst123 · admin / admin123")
        if st.button("Sign in", type="primary", icon=":material/login:", width="stretch"):
            _login(username, password)
            st.rerun()
        if st.session_state.get("login_error"):
            st.error(st.session_state.login_error)

if "token" not in st.session_state:
    st.markdown("# :material/support_agent: :primary[Enterprise AI Assistant]")
    st.caption(":material/login: Sign in from the sidebar. Answers stay inside the documents your role is allowed to read.")
    st.stop()

with st.sidebar:
    role = st.session_state.role
    st.markdown(f":material/person: **{st.session_state.display_name}**")
    st.badge(role, color=ROLE_COLORS.get(role, "gray"), icon=ROLE_ICONS.get(role, ":material/badge:"))
    if st.button("Log out", icon=":material/logout:", width="stretch"):
        for key in ("token", "role", "display_name", "messages", "pending_hitl", "queued_prompt"):
            st.session_state.pop(key, None)
        st.rerun()
    try:
        health = httpx.get(f"{API_BASE_URL}/api/health", timeout=5).json()
        st.caption(f":material/smart_toy: {health.get('chat_model')}")
        st.caption(f":material/library_books: {health.get('chunks')} documents indexed")
        if health.get("langsmith"):
            st.badge("LangSmith on", color="green", icon=":material/monitoring:")
        else:
            st.badge("LangSmith off", color="gray", icon=":material/monitoring:")
    except httpx.HTTPError:
        st.warning("API is not reachable.")

st.markdown("# :material/support_agent: :primary[Enterprise AI Assistant]")
st.caption(":material/forum: Answers from internal documents. Each agent step appears on the right while it works.")

chat_col, activity_col = st.columns([3, 2], gap="medium")
with activity_col:
    st.markdown("### :material/account_tree: :primary[Agent activity]")
    activity_box = st.empty()
_render_activity(activity_box, [])

with chat_col:
    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"], avatar=AVATARS.get(message["role"])):
            st.markdown(message["content"])
            if message["role"] != "assistant":
                continue
            _validation_badge(message.get("validation") or {})
            for item in message.get("degradation") or []:
                st.warning(item)
            citations = message.get("citations") or []
            if citations:
                with st.expander(f"Evidence · {len(citations)}", icon=":material/description:"):
                    for citation in citations:
                        st.markdown(f"**{citation['title']}**")
                        st.caption(
                            f"{citation['doc_id']} · {citation['document_type']} · "
                            f"{citation['access_level']} · {citation['created_date']}"
                        )
                        if citation.get("snippet"):
                            st.markdown(citation["snippet"])
            if message.get("activities"):
                with st.expander("Trace for this answer", icon=":material/timeline:"):
                    for activity in message["activities"]:
                        st.markdown(f"`{activity['node']}` · {activity['state']}")
                        st.caption(activity["detail"])
            with st.container(horizontal=True):
                if st.button("Helpful", icon=":material/thumb_up:", key=f"up-{index}"):
                    httpx.post(
                        f"{API_BASE_URL}/api/feedback",
                        headers=_auth_headers(),
                        json={"session_id": st.session_state.session_id, "rating": 5, "comment": "helpful"},
                        timeout=10,
                    )
                    st.toast("Thanks. That rating is stored for the next turn.")
                if st.button("Not helpful", icon=":material/thumb_down:", key=f"down-{index}"):
                    httpx.post(
                        f"{API_BASE_URL}/api/feedback",
                        headers=_auth_headers(),
                        json={"session_id": st.session_state.session_id, "rating": 1, "comment": "not helpful"},
                        timeout=10,
                    )
                    st.toast("Recorded. The next answer will be steered to be shorter and more cited.")

    if st.session_state.pending_hitl:
        st.warning(st.session_state.pending_hitl.get("reason", "Approval required."))
        with st.container(horizontal=True):
            approved = st.button("Approve reindex", type="primary", icon=":material/check:")
            rejected = st.button("Reject", icon=":material/close:")
        if approved or rejected:
            with st.chat_message("assistant", avatar=AVATARS["assistant"]):
                answer_box = st.empty()
            _send(None, {"approved": approved}, activity_box, answer_box)
            st.rerun()

    queued = st.session_state.get("queued_prompt")
    if not st.session_state.messages and not queued and not st.session_state.pending_hitl:
        st.caption(":material/lightbulb: Start with one of these, or type your own question.")
        starters = STARTERS.get(st.session_state.role, STARTERS["viewer"])
        selected = st.pills("Suggestions", list(starters), selection_mode="single", label_visibility="collapsed")
        if selected:
            st.session_state.queued_prompt = starters[selected]
            st.rerun()

    typed = st.chat_input(
        "Ask about policies, incidents, the directory, or a reindex",
        submit_mode="disable",
    )
    prompt = queued or typed
    if queued:
        st.session_state.queued_prompt = None
    if prompt:
        with st.chat_message("user", avatar=AVATARS["user"]):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar=AVATARS["assistant"]):
            answer_box = st.empty()
        _send(prompt, None, activity_box, answer_box)
        st.rerun()
