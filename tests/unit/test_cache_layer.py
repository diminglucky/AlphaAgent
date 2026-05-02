"""Tests for libs/infra/cache.py (memory + Redis fallback semantics)."""

from __future__ import annotations

import time

from libs.infra import cache as cache_mod


def setup_function(_):
    cache_mod.reset_cache()


def test_default_is_memory_when_no_redis_url(monkeypatch):
    monkeypatch.delenv("QUANT_REDIS_URL", raising=False)
    c = cache_mod.get_cache()
    assert c.name == "memory"


def test_set_get_delete_memory():
    c = cache_mod.get_cache()
    hit, _ = c.get("k1")
    assert hit is False

    c.set("k1", {"a": 1, "b": [2, 3]}, ttl_seconds=10)
    hit, val = c.get("k1")
    assert hit is True
    assert val == {"a": 1, "b": [2, 3]}

    c.delete("k1")
    hit, _ = c.get("k1")
    assert hit is False


def test_ttl_expiry():
    c = cache_mod.get_cache()
    c.set("k_exp", "value", ttl_seconds=0.01)
    time.sleep(0.05)
    hit, _ = c.get("k_exp")
    assert hit is False


def test_stats_increment():
    c = cache_mod.get_cache()
    c.set("hit", 1, ttl_seconds=10)
    c.get("hit")
    c.get("miss")
    s = c.stats()
    assert s["hits"] >= 1
    assert s["misses"] >= 1
    assert 0.0 <= s["hit_rate"] <= 1.0


def test_redis_url_unreachable_falls_back(monkeypatch):
    """Bogus Redis URL must fall back to memory without raising."""
    monkeypatch.setenv("QUANT_REDIS_URL", "redis://127.0.0.1:1/0")
    c = cache_mod.get_cache()
    # Either redis package is missing or connection fails — either way we get memory.
    assert c.name == "memory"
    c.set("x", 1, ttl_seconds=5)
    hit, val = c.get("x")
    assert hit is True
    assert val == 1
