"""Runtime LLM configuration + connectivity tests.

Provides a UI-friendly way to switch between DeepSeek / OpenAI / Qwen /
Ollama without restarting the server. Includes a `/test` endpoint that
performs an actual API call (chat + tool-calling) so the user can verify
their key works end-to-end.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from apps.api.app.core.auth import AuthenticatedUser, get_current_user, require_admin
from libs.llm_analyst.llm_client import LLMClient, LLMConfig, LLMProvider
from libs.llm_analyst.runtime_config import (
    clear_override,
    get_override,
    masked_view,
    set_override,
)

router = APIRouter(prefix="/llm", tags=["llm"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LLMConfigUpdate(BaseModel):
    provider: Optional[str] = Field(None, description="openai | deepseek | qwen | ollama | keyword")
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    timeout: Optional[int] = None


# ---------------------------------------------------------------------------
# GET / POST current config
# ---------------------------------------------------------------------------

def _build_config_view() -> dict:
    """Pure helper used both by GET endpoint and by mutating endpoints."""
    cfg = LLMConfig()
    presets = _provider_presets()
    return {
        "effective": {
            "provider": cfg.provider.value,
            "model": cfg.model,
            "base_url": cfg.base_url,
            "temperature": cfg.temperature,
            "timeout": cfg.timeout,
            "api_key_set": bool(cfg.api_key),
            "api_key_preview": (
                cfg.api_key[:6] + "..." + cfg.api_key[-4:]
                if cfg.api_key and len(cfg.api_key) > 12 else
                "***" if cfg.api_key else ""
            ),
            "is_llm_available": LLMClient(cfg).is_llm_available(),
        },
        "runtime_override": masked_view(),
        "presets": presets,
        "providers": [p.value for p in LLMProvider],
    }


@router.get("/config")
def get_config(user: AuthenticatedUser = Depends(get_current_user)) -> dict:
    """Return current effective config (api_key masked)."""
    return _build_config_view()


@router.post("/config")
def update_config(
    payload: LLMConfigUpdate,
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    """Update runtime override. Empty fields keep prior values. Admin only."""
    set_override(
        provider=payload.provider,
        model=payload.model,
        api_key=payload.api_key,
        base_url=payload.base_url,
        temperature=payload.temperature,
        timeout=payload.timeout,
    )
    return _build_config_view()


@router.delete("/config")
def reset_config(user: AuthenticatedUser = Depends(require_admin)) -> dict:
    """Clear runtime override and revert to env-var / defaults. Admin only."""
    clear_override()
    return _build_config_view()


# ---------------------------------------------------------------------------
# Connectivity tests
# ---------------------------------------------------------------------------

def _run_chat_test(client: LLMClient) -> dict:
    import time
    t0 = time.monotonic()
    try:
        text = client.chat(
            system_prompt="你是一个简洁的助手。",
            user_prompt="用一句话回答：1+1 等于几？",
        )
        return {
            "ok": bool(text) and "[LLM error" not in text,
            "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            "response": text[:200] if text else "",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc),
                "duration_ms": round((time.monotonic() - t0) * 1000, 1)}


def _run_tool_calling_test(client: LLMClient) -> dict:
    import time
    t0 = time.monotonic()
    try:
        from libs.agents import get_default_registry
        reg = get_default_registry()
        tools = reg.to_openai_tools(["get_realtime_quote"])
        resp = client.chat_with_tools(
            messages=[
                {"role": "system", "content": "需要时调用工具。"},
                {"role": "user", "content": "查一下 600519.SH 的实时报价。"},
            ],
            tools=tools,
        )
        called = bool(resp.get("tool_calls"))
        return {
            "ok": called,
            "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            "tool_calls": [
                {"name": tc.get("function", {}).get("name"),
                 "arguments": tc.get("function", {}).get("arguments")}
                for tc in (resp.get("tool_calls") or [])
            ],
            "content": (resp.get("content") or "")[:200],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc),
                "duration_ms": round((time.monotonic() - t0) * 1000, 1)}


def _run_agent_test() -> dict:
    import time
    t0 = time.monotonic()
    try:
        from libs.agents.research_analyst import ResearchAnalystAgent
        from apps.api.app.db.session import session_scope
        with session_scope() as session:
            run = ResearchAnalystAgent().run(
                "对 002230.SZ 做技术面快速评估并给出 BUY/HOLD/SELL。",
                context={"db": session, "symbol": "002230.SZ"},
            )
        return {
            "ok": run.status == "success",
            "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            "llm_powered": run.llm_powered,
            "tool_calls_made": run.tool_calls_made,
            "status": run.status,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc),
                "duration_ms": round((time.monotonic() - t0) * 1000, 1)}


@router.post("/test")
def test_llm(
    level: str = Query("quick", description="quick|standard|full"),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    """Verify config with real API call(s).

    Levels:
    - **quick**     : chat only (~1-3 s) — fastest sanity check
    - **standard**  : chat + tool_calling in parallel (~2-4 s)
    - **full**      : all 3 tests in parallel (~5-10 s)
    """
    import concurrent.futures as cf

    cfg = LLMConfig()
    client = LLMClient(cfg)
    result = {
        "provider": cfg.provider.value,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "is_llm_available": client.is_llm_available(),
        "level": level,
        "tests": {},
    }

    if not client.is_llm_available():
        result["tests"]["chat"] = {
            "ok": False, "error": "LLM not configured (no api_key for provider)",
        }
        return result

    if level == "quick":
        result["tests"]["chat"] = _run_chat_test(client)
        return result

    # standard / full — run tests in parallel
    tasks: dict[str, callable] = {
        "chat": lambda: _run_chat_test(client),
        "tool_calling": lambda: _run_tool_calling_test(client),
    }
    if level == "full":
        tasks["agent_run"] = _run_agent_test

    with cf.ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {name: pool.submit(fn) for name, fn in tasks.items()}
        for name, fut in futures.items():
            try:
                result["tests"][name] = fut.result(timeout=120)
            except Exception as exc:  # noqa: BLE001
                result["tests"][name] = {"ok": False, "error": str(exc)}

    return result


# ---------------------------------------------------------------------------
# Presets — shown in UI
# ---------------------------------------------------------------------------

def _provider_presets() -> dict:
    return {
        "deepseek": {
            "label": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "models": ["deepseek-chat", "deepseek-reasoner"],
            "default_model": "deepseek-chat",
            "key_help": "在 https://platform.deepseek.com 获取 sk- 开头的 API key",
            "supports_tools": True,
        },
        "openai": {
            "label": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            "default_model": "gpt-4o-mini",
            "key_help": "在 https://platform.openai.com/api-keys 获取 sk- 开头的 key",
            "supports_tools": True,
        },
        "qwen": {
            "label": "阿里云百炼 Qwen",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "models": ["qwen-plus", "qwen-max", "qwen-turbo"],
            "default_model": "qwen-plus",
            "key_help": "在 https://bailian.console.aliyun.com 获取 sk- 开头的 DashScope key",
            "supports_tools": True,
        },
        "ollama": {
            "label": "本地 Ollama",
            "base_url": "http://localhost:11434/v1",
            "models": ["qwen2.5:7b", "qwen2.5:14b", "llama3.1:8b"],
            "default_model": "qwen2.5:7b",
            "key_help": "本机运行 ollama，无需 API key（填任意值即可启用）",
            "supports_tools": True,
        },
        "keyword": {
            "label": "无 LLM（确定性 Fallback）",
            "key_help": "Agent 使用确定性 fallback 计划，不调用 LLM",
            "supports_tools": False,
        },
    }
