"""Runtime LLM configuration override.

Allows changing provider / API key / model at runtime via REST endpoint
without server restart. Persists to a JSON file under data/ so changes
survive process restart.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

_LOCK = threading.RLock()
_OVERRIDE: dict | None = None
_OVERRIDE_MTIME: float = 0.0
_PERSIST_PATH = Path(
    os.getenv("QUANT_LLM_CONFIG_PATH", "data/llm_runtime.json")
)


def _load_from_disk() -> dict:
    if not _PERSIST_PATH.exists():
        return {}
    try:
        return json.loads(_PERSIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_to_disk(data: dict) -> None:
    """原子写入：先写临时文件，再重命名，避免读到一半的状态"""
    _PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PERSIST_PATH.with_suffix(_PERSIST_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PERSIST_PATH)
    # 限制权限（防止 API Key 被其他用户读取）
    try:
        os.chmod(_PERSIST_PATH, 0o600)
    except Exception:
        pass


def _disk_mtime() -> float:
    try:
        return _PERSIST_PATH.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def get_override() -> dict:
    """Return the current runtime override.

    在多 worker 场景下，当文件 mtime 变化时自动重新加载，避免某个 worker
    持有过期配置（例如用户在前端改了 API Key 后另一个 worker 用旧 key）。
    """
    global _OVERRIDE, _OVERRIDE_MTIME
    with _LOCK:
        cur_mtime = _disk_mtime()
        if _OVERRIDE is None or cur_mtime > _OVERRIDE_MTIME:
            _OVERRIDE = _load_from_disk()
            _OVERRIDE_MTIME = cur_mtime
        return dict(_OVERRIDE)


def set_override(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    timeout: Optional[int] = None,
    persist: bool = True,
) -> dict:
    """Update runtime override. None values leave existing settings untouched."""
    global _OVERRIDE, _OVERRIDE_MTIME
    with _LOCK:
        cur = get_override()
        if provider is not None:
            cur["provider"] = provider.lower()
        if model is not None:
            cur["model"] = model
        if api_key is not None:
            cur["api_key"] = api_key
        if base_url is not None:
            cur["base_url"] = base_url or None
        if temperature is not None:
            cur["temperature"] = float(temperature)
        if timeout is not None:
            cur["timeout"] = int(timeout)
        _OVERRIDE = cur
        if persist:
            try:
                _save_to_disk(cur)
                _OVERRIDE_MTIME = _disk_mtime()
            except Exception:
                pass
    return dict(cur)


def clear_override(persist: bool = True) -> None:
    global _OVERRIDE, _OVERRIDE_MTIME
    with _LOCK:
        _OVERRIDE = {}
        _OVERRIDE_MTIME = 0.0
        if persist and _PERSIST_PATH.exists():
            try:
                _PERSIST_PATH.unlink()
            except Exception:
                pass


def masked_view() -> dict:
    """Safe-to-render config (api_key redacted)."""
    cfg = get_override()
    out = dict(cfg)
    if out.get("api_key"):
        k = out["api_key"]
        out["api_key"] = (k[:6] + "..." + k[-4:]) if len(k) > 12 else "***"
        out["api_key_set"] = True
    else:
        out["api_key_set"] = False
    return out
