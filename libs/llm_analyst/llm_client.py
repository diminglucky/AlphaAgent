"""LLM client abstraction supporting multiple providers."""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any, Optional


class LLMProvider(str, Enum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    OLLAMA = "ollama"
    KEYWORD = "keyword"  # fallback, no API needed


class LLMConfig:
    """LLM provider configuration. Runtime override > env vars."""

    def __init__(self) -> None:
        # Runtime override (set via REST endpoint or persisted JSON) takes
        # precedence over environment variables, allowing key rotation
        # without restart.
        from libs.llm_analyst.runtime_config import get_override
        ov = get_override()

        self.provider: LLMProvider = LLMProvider(
            (ov.get("provider") or os.getenv("QUANT_LLM_PROVIDER", "keyword")).lower()
        )
        self.model: str = ov.get("model") or os.getenv("QUANT_LLM_MODEL", "")
        self.api_key: str = ov.get("api_key") or os.getenv("QUANT_LLM_API_KEY", "")
        self.base_url: Optional[str] = (
            ov.get("base_url") or os.getenv("QUANT_LLM_BASE_URL") or None
        )
        self.timeout: int = int(ov.get("timeout") or os.getenv("QUANT_LLM_TIMEOUT", "30"))
        self.temperature: float = float(
            ov.get("temperature") if ov.get("temperature") is not None
            else os.getenv("QUANT_LLM_TEMPERATURE", "0.2")
        )

        # Provider-specific defaults
        if self.provider == LLMProvider.DEEPSEEK and not self.base_url:
            self.base_url = "https://api.deepseek.com/v1"
            if not self.model:
                self.model = "deepseek-chat"
        elif self.provider == LLMProvider.QWEN and not self.base_url:
            self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            if not self.model:
                self.model = "qwen-plus"
        elif self.provider == LLMProvider.OLLAMA and not self.base_url:
            self.base_url = "http://localhost:11434/v1"
            if not self.model:
                self.model = "qwen2.5:7b"
        elif self.provider == LLMProvider.OPENAI and not self.model:
            self.model = "gpt-4o-mini"


class LLMClient:
    """
    Unified LLM client.

    Supports OpenAI-compatible APIs (OpenAI, DeepSeek, Qwen via DashScope,
    Ollama) and a keyword-only fallback that requires no API key.
    """

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self._cfg = config or LLMConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def provider(self) -> LLMProvider:
        return self._cfg.provider

    def is_llm_available(self) -> bool:
        """Return True when a real LLM is configured."""
        if self._cfg.provider == LLMProvider.KEYWORD:
            return False
        if self._cfg.provider == LLMProvider.OLLAMA:
            return True  # no key required
        return bool(self._cfg.api_key)

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send a chat completion request and return the text response.
        Falls back to empty string on errors.
        """
        if not self.is_llm_available():
            return ""
        try:
            return self._openai_compatible_chat(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001
            return f"[LLM error: {exc}]"

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        """OpenAI-compatible function calling.

        Returns: {'content': str, 'tool_calls': list[{'id','function':{'name','arguments'}}]}
        """
        if not self.is_llm_available():
            return {"content": "", "tool_calls": []}
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for LLM calls") from exc

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._cfg.api_key:
            headers["Authorization"] = f"Bearer {self._cfg.api_key}"

        base = self._cfg.base_url or "https://api.openai.com/v1"
        url = base.rstrip("/") + "/chat/completions"

        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": self._cfg.temperature,
        }
        resp = httpx.post(url, headers=headers, json=payload, timeout=self._cfg.timeout)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        return {
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
        }

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """
        Send a chat completion request and parse the JSON response.
        Returns an empty dict on parse errors.
        """
        raw = self.chat(system_prompt, user_prompt + "\n\n请只输出 JSON，不要添加任何额外的说明文字。")
        if not raw:
            return {}
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _openai_compatible_chat(self, system_prompt: str, user_prompt: str) -> str:
        """Call an OpenAI-compatible /v1/chat/completions endpoint."""
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx is required for LLM calls: pip install httpx"
            ) from exc

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._cfg.api_key:
            headers["Authorization"] = f"Bearer {self._cfg.api_key}"

        base = self._cfg.base_url or "https://api.openai.com/v1"
        url = base.rstrip("/") + "/chat/completions"

        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._cfg.temperature,
        }

        resp = httpx.post(url, headers=headers, json=payload, timeout=self._cfg.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
