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
    _PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PERSIST_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")


def get_override() -> dict:
    """Return the current runtime override (loads from disk on first call)."""
    global _OVERRIDE
    with _LOCK:
        if _OVERRIDE is None:
            _OVERRIDE = _load_from_disk()
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
    global _OVERRIDE
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
            except Exception:
                pass
    return dict(cur)


def clear_override(persist: bool = True) -> None:
    global _OVERRIDE
    with _LOCK:
        _OVERRIDE = {}
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
