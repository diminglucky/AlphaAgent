"""Generic key/value cache with optional Redis backend (Design Doc §10.2).

Behaviour:
- If `QUANT_REDIS_URL` is set, attempts to connect to Redis and uses it.
- On any failure (no `redis` package installed, connection refused, timeout)
  falls back transparently to the in-process `_TTLCache`.
- Public API:
        cache = get_cache()
        cache.get(key) -> (hit, value)
        cache.set(key, value, ttl_seconds=60)
        cache.delete(key)
        cache.stats() -> dict

Values are JSON-serialised when written to Redis. Non-JSON-serialisable values
fall back to the in-process cache for that single key.

This module is import-time safe; it never raises if redis is missing or down.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Optional, Tuple

log = logging.getLogger("quant.cache")


# ---------------------------------------------------------------------------
# In-process fallback (TTL + LRU)
# ---------------------------------------------------------------------------

class _MemoryCache:
    name = "memory"

    def __init__(self, max_size: int = 4096) -> None:
        self.max_size = max_size
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Tuple[bool, Any]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return False, None
            expires_at, value = entry
            if expires_at and time.monotonic() > expires_at:
                self._data.pop(key, None)
                self.misses += 1
                return False, None
            self._data.move_to_end(key)
            self.hits += 1
            return True, value

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = 60.0) -> None:
        with self._lock:
            expires_at = (time.monotonic() + ttl_seconds) if ttl_seconds else 0.0
            self._data[key] = (expires_at, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "backend": self.name,
                "size": len(self._data),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": (self.hits / total) if total else 0.0,
            }


# ---------------------------------------------------------------------------
# Redis backend (best-effort)
# ---------------------------------------------------------------------------

class _RedisCache:
    name = "redis"

    def __init__(self, url: str, prefix: str = "quant:") -> None:
        import redis  # type: ignore  # imported lazily

        self._prefix = prefix
        self._client = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        # ping eagerly so we fail fast and the factory can fall back
        self._client.ping()
        # local stats (Redis-side stats need INFO; expensive)
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        self._fallback = _MemoryCache(max_size=512)  # for non-json values

    def _k(self, key: str) -> str:
        return self._prefix + key

    def get(self, key: str) -> Tuple[bool, Any]:
        # First check JSON path on Redis
        try:
            raw = self._client.get(self._k(key))
        except Exception as exc:  # noqa: BLE001
            log.warning("redis get failed: %s; falling back to memory", exc)
            return self._fallback.get(key)
        if raw is None:
            # also check fallback (for non-json keys)
            hit, val = self._fallback.get(key)
            with self._lock:
                if hit:
                    self.hits += 1
                else:
                    self.misses += 1
            return hit, val
        try:
            value = json.loads(raw)
        except Exception:  # noqa: BLE001
            value = raw  # raw bytes, return as-is
        with self._lock:
            self.hits += 1
        return True, value

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = 60.0) -> None:
        try:
            payload = json.dumps(value, default=str)
        except (TypeError, ValueError):
            # not JSON-serialisable — keep in-memory only
            self._fallback.set(key, value, ttl_seconds=ttl_seconds)
            return
        try:
            ttl = int(ttl_seconds) if ttl_seconds else 0
            if ttl > 0:
                self._client.setex(self._k(key), ttl, payload)
            else:
                self._client.set(self._k(key), payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("redis set failed: %s; falling back to memory", exc)
            self._fallback.set(key, value, ttl_seconds=ttl_seconds)

    def delete(self, key: str) -> None:
        try:
            self._client.delete(self._k(key))
        except Exception:  # noqa: BLE001
            pass
        self._fallback.delete(key)

    def clear(self) -> None:
        # Only clear our prefix space (best-effort; SCAN, not FLUSHDB)
        try:
            for k in self._client.scan_iter(self._prefix + "*"):
                self._client.delete(k)
        except Exception:  # noqa: BLE001
            pass
        self._fallback.clear()

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "backend": self.name,
                "prefix": self._prefix,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": (self.hits / total) if total else 0.0,
                "fallback": self._fallback.stats(),
            }


# ---------------------------------------------------------------------------
# Factory + module singleton
# ---------------------------------------------------------------------------

_GLOBAL: Any = None
_INIT_LOCK = threading.Lock()


def get_cache():
    """Return the process-global cache instance."""
    global _GLOBAL
    if _GLOBAL is not None:
        return _GLOBAL
    with _INIT_LOCK:
        if _GLOBAL is not None:
            return _GLOBAL
        url = os.getenv("QUANT_REDIS_URL", "").strip()
        if url:
            try:
                _GLOBAL = _RedisCache(url)
                log.info("Using Redis cache at %s", url)
                return _GLOBAL
            except Exception as exc:  # noqa: BLE001
                log.warning("Redis at %s unavailable (%s); falling back to memory.", url, exc)
        _GLOBAL = _MemoryCache()
        return _GLOBAL


def reset_cache() -> None:
    """Reset module-level cache (used by tests)."""
    global _GLOBAL
    with _INIT_LOCK:
        if _GLOBAL is not None and hasattr(_GLOBAL, "clear"):
            _GLOBAL.clear()
        _GLOBAL = None
