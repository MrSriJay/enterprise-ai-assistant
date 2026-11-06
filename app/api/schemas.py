"""Request bodies for the HTTP API."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

from app.config import get_settings

_SESSION = re.compile(r"[A-Za-z0-9_-]{8,64}")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ResumeRequest(BaseModel):
    approved: bool


class ChatRequest(BaseModel):
    message: str = ""
    session_id: str | None = None
    resume: ResumeRequest | None = None

    @model_validator(mode="after")
    def check(self) -> "ChatRequest":
        settings = get_settings()
        if self.resume is None and not self.message.strip():
            raise ValueError("Message is required.")
        if len(self.message) > settings.max_message_chars:
            raise ValueError("Message is too long.")
        if "\x00" in self.message:
            raise ValueError("Message contains invalid characters.")
        if self.session_id and not _SESSION.fullmatch(self.session_id):
            raise ValueError("Invalid session id.")
        return self


class FeedbackRequest(BaseModel):
    session_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def check_session(self) -> "FeedbackRequest":
        if not _SESSION.fullmatch(self.session_id):
            raise ValueError("Invalid session id.")
        return self
