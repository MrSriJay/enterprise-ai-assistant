"""Application errors that map cleanly onto HTTP responses."""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, *, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}

    def as_dict(self) -> dict:
        body = {"error": self.code, "message": self.message}
        body.update(self.extra)
        return body
