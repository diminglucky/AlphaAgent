"""Process-safe runtime configuration persisted as JSON.

This stores operator-controlled settings that must change without a server
restart. Secrets are kept out of API responses by each route's view layer.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_CONFIG: dict[str, Any] | None = None
_CONFIG_MTIME: float = 0.0


def _persist_path() -> Path:
    return Path(os.getenv("QUANT_RUNTIME_CONFIG_PATH", "data/runtime_config.json"))


def _load_from_disk() -> dict[str, Any]:
    path = _persist_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_to_disk(data: dict[str, Any]) -> None:
    path = _persist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _disk_mtime() -> float:
    try:
        return _persist_path().stat().st_mtime
    except FileNotFoundError:
        return 0.0


def get_runtime_config() -> dict[str, Any]:
    global _CONFIG, _CONFIG_MTIME
    with _LOCK:
        cur_mtime = _disk_mtime()
        if _CONFIG is None or cur_mtime > _CONFIG_MTIME:
            _CONFIG = _load_from_disk()
            _CONFIG_MTIME = cur_mtime
        return dict(_CONFIG)


def update_runtime_section(section: str, values: dict[str, Any]) -> dict[str, Any]:
    global _CONFIG, _CONFIG_MTIME
    with _LOCK:
        cur = get_runtime_config()
        existing = cur.get(section) or {}
        if not isinstance(existing, dict):
            existing = {}
        existing.update(values)
        cur[section] = {k: v for k, v in existing.items() if v is not None}
        _CONFIG = cur
        _save_to_disk(cur)
        _CONFIG_MTIME = _disk_mtime()
        return dict(cur[section])


def clear_runtime_section(section: str) -> None:
    global _CONFIG, _CONFIG_MTIME
    with _LOCK:
        cur = get_runtime_config()
        cur.pop(section, None)
        _CONFIG = cur
        if cur:
            _save_to_disk(cur)
            _CONFIG_MTIME = _disk_mtime()
            return
        path = _persist_path()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        _CONFIG_MTIME = 0.0


def reset_runtime_config_cache() -> None:
    global _CONFIG, _CONFIG_MTIME
    with _LOCK:
        _CONFIG = None
        _CONFIG_MTIME = 0.0
