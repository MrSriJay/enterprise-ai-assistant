"""Per-user token buckets.

A chat consumes one token. The bucket refills continuously up to a configured
capacity. When it is empty the API returns 429 instead of starting a graph run.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.config import get_settings


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: float
    remaining: float


class TokenBucketLimiter:
    def __init__(self, capacity: float, refill_per_minute: float):
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_minute) / 60.0
        self._buckets: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    def consume(self, key: str, amount: float = 1) -> RateDecision:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = {"tokens": self.capacity, "updated": now}
                self._buckets[key] = bucket
            elapsed = max(0.0, now - bucket["updated"])
            bucket["tokens"] = min(self.capacity, bucket["tokens"] + elapsed * self.refill_per_second)
            bucket["updated"] = now
            if bucket["tokens"] < amount:
                deficit = amount - bucket["tokens"]
                retry = deficit / self.refill_per_second if self.refill_per_second else 60.0
                return RateDecision(False, round(retry, 2), round(bucket["tokens"], 2))
            bucket["tokens"] -= amount
            return RateDecision(True, 0.0, round(bucket["tokens"], 2))

    def reset(self, capacity: float, refill_per_minute: float) -> None:
        with self._lock:
            self.capacity = float(capacity)
            self.refill_per_second = float(refill_per_minute) / 60.0
            self._buckets.clear()


_chat_limiter: TokenBucketLimiter | None = None
_login_limiter: TokenBucketLimiter | None = None


def chat_limiter() -> TokenBucketLimiter:
    global _chat_limiter
    if _chat_limiter is None:
        settings = get_settings()
        _chat_limiter = TokenBucketLimiter(settings.rate_limit_capacity, settings.rate_limit_refill_per_minute)
    return _chat_limiter


def login_limiter() -> TokenBucketLimiter:
    global _login_limiter
    if _login_limiter is None:
        _login_limiter = TokenBucketLimiter(30, 30)
    return _login_limiter
