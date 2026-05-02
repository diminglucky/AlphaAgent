"""Lightweight in-memory rate limiter (token bucket).

Suitable for single-process deployments. Use Redis-based limiting for
multi-worker production setups.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Optional

from fastapi import HTTPException, Request


class TokenBucket:
    """Per-key token bucket: capacity & refill rate per second."""

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = capacity
        self.refill = refill_per_sec
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = Lock()

    def take(self, key: str, tokens: int = 1) -> bool:
        now = time.monotonic()
        with self._lock:
            available, last = self._buckets.get(key, (float(self.capacity), now))
            available = min(self.capacity, available + (now - last) * self.refill)
            if available >= tokens:
                available -= tokens
                self._buckets[key] = (available, now)
                return True
            self._buckets[key] = (available, now)
            return False


# 10 calls per minute per IP for the expensive analyse endpoint (LLM cost guard)
_analyze_limiter = TokenBucket(capacity=10, refill_per_sec=10 / 60)


def rate_limit_analyze(request: Request) -> None:
    """FastAPI dependency to apply rate-limiting on the analyze endpoint."""
    client = request.client.host if request.client else "anonymous"
    key = request.headers.get("X-API-Key", client)
    if not _analyze_limiter.take(key):
        raise HTTPException(
            status_code=429,
            detail="分析请求过于频繁，请稍后再试（默认 10 次/分钟）",
        )
