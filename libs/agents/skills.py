"""Skill system — composable, schema-described tools that agents can invoke.

Each Skill is a callable bundled with a JSON-schema describing parameters
and return shape, so agents (LLM-powered or heuristic) can:
1. Select which tool to call.
2. Validate parameters.
3. Read structured outputs.

This mirrors the OpenAI/Anthropic function-calling API spec, making LLM
integration trivial when an API key is configured, while keeping the
fallback path runnable.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("quant.skills")


@dataclass
class Skill:
    """A typed, named tool an agent can invoke."""
    name: str
    description: str
    parameters: dict           # JSON schema (OpenAI tool format)
    handler: Callable[..., Any]
    category: str = "general"
    requires_db: bool = False
    requires_market: bool = False

    def to_openai_tool(self) -> dict:
        """Render as OpenAI tool-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_tool(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


@dataclass
class ToolCall:
    name: str
    arguments: dict
    call_id: Optional[str] = None


@dataclass
class ToolResult:
    call_id: Optional[str]
    name: str
    output: Any
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_message_content(self) -> str:
        """Stringify for inclusion in LLM messages."""
        payload = {"output": self.output} if self.error is None else {"error": self.error}
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            return str(payload)


class SkillRegistry:
    """Container for discoverable agent skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            log.debug("overriding existing skill: %s", skill.name)
        self._skills[skill.name] = skill

    def register_many(self, skills: list[Skill]) -> None:
        for s in skills:
            self.register(s)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def list(self, category: Optional[str] = None) -> list[Skill]:
        if category is None:
            return list(self._skills.values())
        return [s for s in self._skills.values() if s.category == category]

    def to_openai_tools(self, names: Optional[list[str]] = None) -> list[dict]:
        skills = (
            [self._skills[n] for n in names if n in self._skills]
            if names else list(self._skills.values())
        )
        return [s.to_openai_tool() for s in skills]

    def execute(self, call: ToolCall, *, context: Optional[dict] = None) -> ToolResult:
        """Run a single tool call. Catches errors and times execution."""
        skill = self.get(call.name)
        if skill is None:
            return ToolResult(
                call_id=call.call_id, name=call.name, output=None,
                error=f"unknown skill: {call.name}",
            )
        t0 = time.monotonic()
        try:
            kwargs = dict(call.arguments or {})
            if context:
                # Inject DB / market only if the skill declared requires_*
                if skill.requires_db and "db" in context:
                    kwargs["_db"] = context["db"]
                if skill.requires_market and "market" in context:
                    kwargs["_market"] = context["market"]
            output = skill.handler(**kwargs)
            return ToolResult(
                call_id=call.call_id, name=call.name, output=output,
                duration_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                call_id=call.call_id, name=call.name, output=None,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )


# ---------------------------------------------------------------------------
# Default registry — populated on first access.
# ---------------------------------------------------------------------------

_default_registry: Optional[SkillRegistry] = None


def get_default_registry() -> SkillRegistry:
    """Return the process-wide registry with all built-in skills loaded."""
    global _default_registry
    if _default_registry is None:
        _default_registry = SkillRegistry()
        from libs.agents.skills_market import register_market_skills
        from libs.agents.skills_news import register_news_skills
        from libs.agents.skills_technical import register_technical_skills
        register_market_skills(_default_registry)
        register_news_skills(_default_registry)
        register_technical_skills(_default_registry)
        # portfolio/risk/execution skills 依赖旧 Repository，按需加载
        try:
            from libs.agents.skills_portfolio import register_portfolio_skills
            register_portfolio_skills(_default_registry)
        except Exception:
            pass
        try:
            from libs.agents.skills_risk import register_risk_skills
            register_risk_skills(_default_registry)
        except Exception:
            pass
        try:
            from libs.agents.skills_execution import register_execution_skills
            register_execution_skills(_default_registry)
        except Exception:
            pass
    return _default_registry
