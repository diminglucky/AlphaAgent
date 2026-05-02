"""Agent memory — short-term context + decision history + outcome tracking.

Three layers:
1. ScratchpadMemory   : within-run notes (volatile, per-agent-run)
2. EpisodicMemory     : recent decisions (last N runs, in-process)
3. PersistentMemory   : optional DB-backed log of every decision + outcome
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class MemoryEntry:
    timestamp: datetime
    agent: str
    role: str            # "observation" | "thought" | "action" | "decision" | "outcome"
    content: Any
    tags: list[str] = field(default_factory=list)


class AgentMemory:
    """In-process memory with ring-buffer episodic store."""

    def __init__(self, episodic_capacity: int = 100) -> None:
        self._episodic: deque[MemoryEntry] = deque(maxlen=episodic_capacity)
        self._scratchpad: dict[str, list[MemoryEntry]] = {}  # run_id -> entries

    # --- scratchpad (per-run) ---
    def scratchpad_append(self, run_id: str, entry: MemoryEntry) -> None:
        self._scratchpad.setdefault(run_id, []).append(entry)

    def scratchpad_get(self, run_id: str) -> list[MemoryEntry]:
        return list(self._scratchpad.get(run_id, []))

    def scratchpad_clear(self, run_id: str) -> None:
        self._scratchpad.pop(run_id, None)

    # --- episodic (persistent within process) ---
    def remember(self, entry: MemoryEntry) -> None:
        self._episodic.append(entry)

    def recall(
        self,
        agent: Optional[str] = None,
        role: Optional[str] = None,
        last_n: int = 10,
        tag: Optional[str] = None,
    ) -> list[MemoryEntry]:
        items = list(self._episodic)
        if agent:
            items = [e for e in items if e.agent == agent]
        if role:
            items = [e for e in items if e.role == role]
        if tag:
            items = [e for e in items if tag in e.tags]
        return items[-last_n:]

    def summary(self) -> dict:
        agents = sorted({e.agent for e in self._episodic})
        roles = sorted({e.role for e in self._episodic})
        return {
            "n_entries": len(self._episodic),
            "n_agents": len(agents),
            "agents": agents,
            "roles": roles,
        }


# Process-wide singleton
_global_memory: Optional[AgentMemory] = None


def get_global_memory() -> AgentMemory:
    global _global_memory
    if _global_memory is None:
        _global_memory = AgentMemory(episodic_capacity=500)
    return _global_memory
