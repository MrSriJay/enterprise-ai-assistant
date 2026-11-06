"""HTTP API for login, chat, feedback, and health."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from app.agents.graph import get_graph, run_config
from app.agents.state import conversation_thread, initial_state
from app.auth.tokens import issue_token, read_token
from app.auth.users import User, authenticate
from app.errors import AppError
from app.logging_config import get_logger
from app.memory.store import add_feedback, ensure_session, feedback_note, long_term_summary, recent_messages
from app.observability import close_event_stream, open_event_stream
from app.security.rate_limit import chat_limiter, login_limiter
from app.api.schemas import ChatRequest, FeedbackRequest, LoginRequest

logger = get_logger(__name__)
router = APIRouter()


def require_user(authorization: str | None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError("unauthorized", "Login required.", 401)
    user = read_token(authorization.split(" ", 1)[1].strip())
    if user is None:
        raise AppError("unauthorized", "Invalid or expired session.", 401)
    return user


@router.post("/api/auth/login")
async def login(body: LoginRequest) -> dict:
    decision = login_limiter().consume(body.username.lower())
    if not decision.allowed:
        raise AppError(
            "rate_limited",
            "Too many login attempts. Please wait and try again.",
            429,
            extra={"retry_after_seconds": decision.retry_after_seconds},
        )
    user = authenticate(body.username, body.password)
    if user is None:
        raise AppError("unauthorized", "Unknown username or password.", 401)
    return {
        "token": issue_token(user),
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
    }


@router.post("/api/chat")
async def chat(body: ChatRequest, authorization: str | None = Header(default=None)) -> StreamingResponse:
    user = require_user(authorization)
    decision = chat_limiter().consume(user.username)
    if not decision.allowed:
        raise AppError(
            "rate_limited",
            "Too many questions. Please wait for the rate limit to refill.",
            429,
            extra={"retry_after_seconds": decision.retry_after_seconds},
        )
    session_id = body.session_id or uuid.uuid4().hex
    ensure_session(session_id, user.user_id)
    thread_id = conversation_thread(user.user_id, session_id)
    graph = get_graph()
    config = run_config(thread_id)
    try:
        snapshot = await graph.aget_state(config)
        pending = _approval_pending(snapshot)
    except Exception:
        logger.exception("Could not read the conversation checkpoint")
        pending = False
    if pending and body.resume is None:
        raise AppError("approval_pending", "Approve or reject the pending action before asking something else.", 409)
    if body.resume is not None and not pending:
        raise AppError("nothing_pending", "There is no action waiting for approval.", 409)

    request_id = uuid.uuid4().hex
    if body.resume is not None:
        await graph.aupdate_state(config, {"approved": body.resume.approved})
        graph_input = None
    else:
        graph_input = initial_state(
            user_id=user.user_id,
            user_role=user.role,
            session_id=session_id,
            request_id=request_id,
            message=body.message,
        )

    stream = _event_stream(
        graph_input,
        config,
        thread_id=thread_id,
        session_id=session_id,
        request_id=request_id,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-RateLimit-Remaining": str(int(decision.remaining)),
            "X-Session-Id": session_id,
        },
    )


@router.post("/api/feedback")
async def feedback(body: FeedbackRequest, authorization: str | None = Header(default=None)) -> dict:
    user = require_user(authorization)
    ensure_session(body.session_id, user.user_id)
    add_feedback(body.session_id, user.user_id, body.rating, body.comment)
    return {"status": "saved", "feedback_note": feedback_note(user.user_id)}


@router.get("/api/sessions/{session_id}")
async def session_memory(session_id: str, authorization: str | None = Header(default=None)) -> dict:
    user = require_user(authorization)
    ensure_session(session_id, user.user_id)
    return {
        "session_id": session_id,
        "history": recent_messages(session_id, user.user_id, limit=20),
        "long_term": long_term_summary(user.user_id),
        "feedback_note": feedback_note(user.user_id),
    }


async def _event_stream(graph_input, config: dict, *, thread_id: str, session_id: str, request_id: str) -> AsyncIterator[str]:
    queue = open_event_stream(thread_id)
    await queue.put({"type": "meta", "session_id": session_id, "request_id": request_id, "thread_id": thread_id})

    async def drive() -> None:
        try:
            result = await get_graph().ainvoke(graph_input, config, durability="sync")
            snapshot = await get_graph().aget_state(config)
            if _approval_pending(snapshot):
                payload = (result or {}).get("hitl") or {"action": "reindex", "reason": "Approval required."}
                await queue.put({"type": "hitl", "payload": payload, "session_id": session_id})
                answer = payload.get("reason") or "This action needs approval before I can continue."
                await queue.put(
                    {
                        "type": "final",
                        "answer": answer,
                        "citations": [],
                        "validation": {"status": "pending_approval"},
                        "degradation": [],
                        "activities": (result or {}).get("activities") or [],
                        "route": (result or {}).get("route"),
                        "intent": (result or {}).get("intent"),
                        "session_id": session_id,
                        "pending_approval": True,
                        "hitl": payload,
                    }
                )
                return
            answer = (result or {}).get("final_answer") or ""
            step = 80
            for start in range(0, len(answer), step):
                await queue.put({"type": "token", "text": answer[start : start + step]})
            await queue.put(
                {
                    "type": "final",
                    "answer": answer,
                    "citations": (result or {}).get("citations") or [],
                    "validation": (result or {}).get("validation") or {},
                    "degradation": (result or {}).get("degradation") or [],
                    "activities": (result or {}).get("activities") or [],
                    "route": (result or {}).get("route"),
                    "intent": (result or {}).get("intent"),
                    "session_id": session_id,
                    "pending_approval": False,
                }
            )
        except Exception as exc:
            logger.exception("Chat run failed", extra={"fields": {"request_id": request_id}})
            await queue.put(
                {
                    "type": "error",
                    "code": "chat_failed",
                    "message": "The assistant hit an unexpected error and stopped safely.",
                    "detail": type(exc).__name__,
                }
            )
        finally:
            await queue.put(None)

    task = asyncio_create(drive())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield _sse(event)
    finally:
        close_event_stream(thread_id)
        if not task.done():
            task.cancel()


def _approval_pending(snapshot) -> bool:
    pending = getattr(snapshot, "next", ()) or ()
    return "approval_wait" in pending


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def asyncio_create(coro):
    import asyncio

    return asyncio.create_task(coro)
