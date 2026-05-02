"""BaseAgent — ReAct loop with tool calling.

Algorithm:
    while step < max_steps and not finished:
        thought  = think(scratchpad, observations)
        action   = decide_next_action(thought)   # tool_call OR final_answer
        if action is final_answer:
            break
        observation = execute_tool(action)
        scratchpad.append(thought, action, observation)
        step += 1

When LLM is configured (`LLMClient.is_llm_available() == True`), we pass
the registered Skills as OpenAI-style tools and let the model do the
reasoning. When LLM is not available, the subclass's `_fallback_plan()`
provides a deterministic plan over the same tools.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from libs.agents.memory import AgentMemory, MemoryEntry, get_global_memory
from libs.agents.skills import (
    SkillRegistry,
    ToolCall,
    ToolResult,
    get_default_registry,
)
from libs.llm_analyst.llm_client import LLMClient

log = logging.getLogger("quant.agent")


@dataclass
class AgentStep:
    step: int
    role: str                       # "thought" | "tool_call" | "tool_result" | "final"
    content: Any
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AgentRun:
    run_id: str
    agent_name: str
    goal: str
    steps: list[AgentStep] = field(default_factory=list)
    final_answer: Optional[Any] = None
    status: str = "running"          # running | success | failed | timeout
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    duration_ms: float = 0.0
    llm_powered: bool = False
    tool_calls_made: int = 0


class BaseAgent:
    """ReAct-style agent. Subclass and implement:
        - `system_prompt()` — role description + protocol
        - `tools()`         — list of skill names to expose
        - `_fallback_plan(goal, ctx)` — deterministic plan when no LLM
    """

    name: str = "base_agent"
    max_steps: int = 6

    def __init__(
        self,
        registry: Optional[SkillRegistry] = None,
        memory: Optional[AgentMemory] = None,
        llm: Optional[LLMClient] = None,
    ) -> None:
        self.registry = registry or get_default_registry()
        self.memory = memory or get_global_memory()
        self.llm = llm or LLMClient()

    # --- subclass hooks ---
    def system_prompt(self) -> str:
        raise NotImplementedError

    def tools(self) -> list[str]:
        """Return names of skills this agent may invoke."""
        return self.registry.names()

    def _fallback_plan(self, goal: str, context: dict) -> list[ToolCall]:
        """Deterministic tool plan when LLM is unavailable."""
        return []

    def _parse_llm_final(self, content: str):
        """Hook for subclasses to convert the LLM's markdown reply into
        a structured object. Return ``None`` to keep the raw string.

        Default behaviour: pass through unchanged.
        """
        return None

    def _summarize_observations(
        self, goal: str, observations: list[ToolResult],
    ) -> dict:
        """Produce final answer from observations (fallback path)."""
        return {
            "summary": "fallback execution complete",
            "observations": [
                {"tool": o.name, "ok": o.error is None, "output": o.output}
                for o in observations
            ],
        }

    # --- main entry ---
    def run(self, goal: str, context: Optional[dict] = None) -> AgentRun:
        run_id = uuid.uuid4().hex[:12]
        ctx = dict(context or {})
        run = AgentRun(
            run_id=run_id, agent_name=self.name, goal=goal,
            llm_powered=self.llm.is_llm_available(),
        )
        t0 = time.monotonic()

        try:
            if run.llm_powered:
                self._run_llm(run, ctx)
            else:
                self._run_fallback(run, ctx)
            run.status = "success"
        except Exception as exc:  # noqa: BLE001
            log.warning("agent[%s] run failed: %s", self.name, exc, exc_info=True)
            run.steps.append(AgentStep(step=len(run.steps), role="final",
                                       content={"error": str(exc)}))
            run.status = "failed"
        finally:
            run.duration_ms = (time.monotonic() - t0) * 1000
            run.finished_at = datetime.now()

        # Emit episodic memory
        self.memory.remember(MemoryEntry(
            timestamp=run.finished_at,
            agent=self.name,
            role="decision",
            content={
                "goal": goal,
                "final": run.final_answer,
                "tool_calls_made": run.tool_calls_made,
                "status": run.status,
            },
            tags=[self.name, run.status],
        ))
        return run

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    def _run_llm(self, run: AgentRun, ctx: dict) -> None:
        tool_specs = self.registry.to_openai_tools(self.tools())
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": run.goal},
        ]

        for step_idx in range(self.max_steps):
            try:
                response = self.llm.chat_with_tools(
                    messages=messages, tools=tool_specs,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("LLM call failed: %s — falling back", exc)
                return self._run_fallback(run, ctx)

            tool_calls = response.get("tool_calls") or []
            content = response.get("content") or ""

            if content:
                run.steps.append(AgentStep(step=step_idx, role="thought", content=content))

            if not tool_calls:
                raw = content or response
                # Allow subclasses to extract structured data from the LLM's
                # free-form markdown reply. Default returns the string as-is.
                try:
                    parsed = self._parse_llm_final(raw)
                except Exception:  # noqa: BLE001
                    parsed = raw
                run.final_answer = parsed if parsed is not None else raw
                run.steps.append(AgentStep(step=step_idx, role="final", content=run.final_answer))
                return

            # Append assistant tool-call message
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"id": tc.get("id"), "type": "function",
                     "function": {"name": tc["function"]["name"],
                                  "arguments": tc["function"]["arguments"]}}
                    for tc in tool_calls
                ],
            })

            # Execute each tool
            for tc in tool_calls:
                fname = tc["function"]["name"]
                fargs = tc["function"]["arguments"]
                if isinstance(fargs, str):
                    try:
                        fargs = json.loads(fargs)
                    except Exception:
                        fargs = {}
                call = ToolCall(name=fname, arguments=fargs, call_id=tc.get("id"))
                run.steps.append(AgentStep(step=step_idx, role="tool_call",
                                           content={"name": fname, "arguments": fargs}))

                result = self.registry.execute(call, context=ctx)
                run.tool_calls_made += 1
                run.steps.append(AgentStep(step=step_idx, role="tool_result",
                                           content={"name": fname, "ok": result.error is None,
                                                    "output": result.output, "error": result.error}))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": result.to_message_content(),
                })

        # Out of steps without a final
        run.final_answer = {"error": "max_steps reached without final answer"}
        run.status = "timeout"

    # ------------------------------------------------------------------
    # Fallback path (LLM not configured)
    # ------------------------------------------------------------------

    def _run_fallback(self, run: AgentRun, ctx: dict) -> None:
        plan = self._fallback_plan(run.goal, ctx)
        observations: list[ToolResult] = []
        for step_idx, call in enumerate(plan):
            run.steps.append(AgentStep(step=step_idx, role="tool_call",
                                       content={"name": call.name, "arguments": call.arguments}))
            result = self.registry.execute(call, context=ctx)
            run.tool_calls_made += 1
            run.steps.append(AgentStep(step=step_idx, role="tool_result",
                                       content={"name": call.name, "ok": result.error is None,
                                                "output": result.output, "error": result.error}))
            observations.append(result)

        final = self._summarize_observations(run.goal, observations)
        run.final_answer = final
        run.steps.append(AgentStep(step=len(run.steps), role="final", content=final))
