"""Hardcoded demo identities.

Option A from the assessment: a fixed user table, not an identity provider.
Passwords are compared as SHA-256 digests so the check itself does not leak
length. This is still a demo table and is not a production user store.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    password: str
    role: str
    display_name: str


USERS: dict[str, User] = {
    "viewer": User("user-viewer", "viewer", "viewer123", "viewer", "Riley Viewer"),
    "analyst": User("user-analyst", "analyst", "analyst123", "analyst", "Jordan Analyst"),
    "admin": User("user-admin", "admin", "admin123", "administrator", "Avery Admin"),
}


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def authenticate(username: str, password: str) -> User | None:
    user = USERS.get(username.strip().lower())
    candidate = user.password if user else "dummy-password-not-a-user"
    matches = hmac.compare_digest(_digest(candidate), _digest(password))
    if user and matches:
        return user
    return None
