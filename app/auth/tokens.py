"""Signed bearer tokens for the demo login flow."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from app.auth.users import USERS, User
from app.config import get_settings

TOKEN_TTL_SECONDS = 12 * 60 * 60


def issue_token(user: User) -> str:
    expiry = int(time.time()) + TOKEN_TTL_SECONDS
    nonce = secrets.token_hex(8)
    body = f"{user.username}|{user.role}|{expiry}|{nonce}"
    signature = _sign(body)
    raw = f"{body}|{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def read_token(token: str) -> User | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        username, role, expiry, nonce, signature = raw.split("|")
    except (ValueError, UnicodeError):
        return None
    body = f"{username}|{role}|{expiry}|{nonce}"
    if not hmac.compare_digest(_sign(body), signature):
        return None
    try:
        if int(expiry) < int(time.time()):
            return None
    except ValueError:
        return None
    user = USERS.get(username)
    if user is None or user.role != role:
        return None
    return user


def _sign(body: str) -> str:
    secret = get_settings().session_secret.encode("utf-8")
    return hmac.new(secret, body.encode("utf-8"), hashlib.sha256).hexdigest()
