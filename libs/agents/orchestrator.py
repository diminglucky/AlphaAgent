"""AgentOrchestrator — coordinates multi-agent workflows.

Currently supports two flagship workflows:
- daily_brief        : MarketScout → PortfolioGuardian → consolidate
- on_demand_research : run a deep-research agent for a specific symbol
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from libs.agents.base_agent import AgentRun
from libs.agents.market_scout import MarketScoutAgent
from libs.agents.portfolio_guardian import PortfolioGuardianAgent


class AgentOrchestrator:
    def __init__(self) -> None:
        self.scout = MarketScoutAgent()
        self.guardian = PortfolioGuardianAgent()

    def daily_brief(self, db_session) -> dict:
        """Run scout + guardian and synthesize a unified brief."""
        ctx = {"db": db_session}

        scout_run = self.scout.run(
            goal="为我找出今日 3 只最有买入潜力的 A 股，给出明确建议、置信度、关键指标和风险点。",
            context=ctx,
        )
        guardian_run = self.guardian.run(
            goal="检查我当前所有持仓，找出需要立即减仓或止损的标的并给出理由。",
            context=ctx,
        )

        return {
            "generated_at": datetime.now().isoformat(),
            "llm_powered": scout_run.llm_powered,
            "scout": _summarize_run(scout_run),
            "guardian": _summarize_run(guardian_run),
        }


def _summarize_run(run: AgentRun) -> dict:
    return {
        "agent": run.agent_name,
        "run_id": run.run_id,
        "status": run.status,
        "duration_ms": round(run.duration_ms, 1),
        "tool_calls_made": run.tool_calls_made,
        "final": run.final_answer,
        "trace": [
            {"step": s.step, "role": s.role,
             "content": _truncate(s.content)}
            for s in run.steps
        ],
    }


def _truncate(obj, max_chars: int = 2000):
    """Compress giant tool outputs in the trace."""
    import json
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    if len(s) > max_chars:
        return s[:max_chars] + f"... ({len(s) - max_chars} chars truncated)"
    return obj
