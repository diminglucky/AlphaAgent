"""
Lightweight TTL + LRU cache for market data calls.

Goal: same idea as TradingAgents-CN's Redis layer, but in-process so it
works without external dependencies. Suitable for single-worker servers.

Use as a decorator:

    @ttl_cache(ttl_seconds=60)
    def get_bars(symbol, start, end):
        ...
"""

from __future__ import annotations

import functools
import threading
import time
from collections import OrderedDict
from typing import Any, Callable


class _TTLCache:
    def __init__(self, max_size: int, ttl: float) -> None:
        self.max_size = max_size
        self.ttl = ttl
        self._data: "OrderedDict[Any, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> tuple[bool, Any]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return False, None
            ts, value = entry
            if time.monotonic() - ts > self.ttl:
                self._data.pop(key, None)
                self.misses += 1
                return False, None
            # LRU touch
            self._data.move_to_end(key)
            self.hits += 1
            return True, value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._data),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": (self.hits / (self.hits + self.misses)) if (self.hits + self.misses) else 0.0,
            }


_REGISTERED_CACHES: dict[str, _TTLCache] = {}


def ttl_cache(ttl_seconds: float = 60.0, max_size: int = 256) -> Callable:
    """Decorator factory."""
    def decorator(func: Callable) -> Callable:
        cache = _TTLCache(max_size=max_size, ttl=ttl_seconds)
        _REGISTERED_CACHES[f"{func.__module__}.{func.__qualname__}"] = cache

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (args, tuple(sorted(kwargs.items())))
            hit, value = cache.get(key)
            if hit:
                return value
            value = func(*args, **kwargs)
            cache.set(key, value)
            return value

        wrapper.cache = cache  # type: ignore[attr-defined]
        return wrapper

    return decorator


def cache_stats() -> dict:
    """Aggregate stats across all registered caches."""
    return {name: c.stats() for name, c in _REGISTERED_CACHES.items()}
