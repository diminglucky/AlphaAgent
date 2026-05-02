"""Agentic endpoints — Skills + ReAct agents."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.app.core.auth import AuthenticatedUser, require_trader
from apps.api.app.db.session import get_db
from libs.agents import get_default_registry
from libs.agents.market_scout import MarketScoutAgent
from libs.agents.portfolio_guardian import PortfolioGuardianAgent
from libs.agents.profit_maximizer import ProfitMaximizerAgent
from libs.agents.research_analyst import ResearchAnalystAgent
from libs.agents.orchestrator import AgentOrchestrator
from libs.agents.memory import get_global_memory

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/skills")
def list_skills(category: str | None = Query(None)):
    """Discover all skills agents can call."""
    reg = get_default_registry()
    skills = reg.list(category=category)
    return {
        "count": len(skills),
        "categories": sorted({s.category for s in reg.list()}),
        "skills": [
            {
                "name": s.name,
                "category": s.category,
                "description": s.description,
                "parameters": s.parameters,
                "requires_db": s.requires_db,
            }
            for s in skills
        ],
    }


@router.post("/scout/run")
def run_scout(
    goal: str | None = None,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
):
    """Trigger the autonomous MarketScout agent."""
    g = goal or "为我找出今日 3 只最有买入潜力的 A 股，给出明确建议、置信度、关键指标和风险点。"
    run = MarketScoutAgent().run(g, context={"db": db})
    return _serialize_run(run)


@router.post("/guardian/run")
def run_guardian(
    goal: str | None = None,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
):
    """Trigger the autonomous PortfolioGuardian agent."""
    g = goal or "检查我当前所有持仓，找出需要立即减仓或止损的标的并给出理由。"
    run = PortfolioGuardianAgent().run(g, context={"db": db})
    return _serialize_run(run)


@router.post("/research/{symbol}")
def run_research(
    symbol: str,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
):
    """Deep research on one symbol via ResearchAnalystAgent."""
    goal = f"对 {symbol} 做完整深度研究：技术面、舆情、支撑阻力、是否已持仓，最终给出 BUY/HOLD/SELL 建议。"
    run = ResearchAnalystAgent().run(goal, context={"db": db, "symbol": symbol})
    return _serialize_run(run)


@router.post("/daily-brief")
def daily_brief(
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
):
    """Run scout + guardian end-to-end and return a unified brief."""
    return AgentOrchestrator().daily_brief(db_session=db)


@router.post("/profit-maximizer/run")
def run_profit_maximizer(
    goal: str | None = None,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
):
    """一体化决策 Agent：同时输出「买什么」+「卖什么」+「仓位」.

    Output (final_answer):
      - buy_actions: list of BUY proposals with predicted_return, weight, qty
      - sell_actions: list of SELL/REDUCE_HALF (proactive + reactive)
      - watch_list: early warnings, no trade yet
      - hold_list: healthy holdings
      - cash_to_deploy / sell_first / expected_portfolio_alpha / summary
    """
    g = goal or (
        "给我一份今日作战计划：买哪几只（预期上涨）、卖哪几只（预警或止损）、"
        "每一动作需仓位大小与明确理由，调估未来5、20个交易日预期收益。"
    )
    run = ProfitMaximizerAgent().run(g, context={"db": db})
    return _serialize_run(run)


@router.get("/memory")
def get_memory(
    agent: str | None = None,
    role: str | None = None,
    last_n: int = 50,
):
    """Inspect agent decision history."""
    mem = get_global_memory()
    entries = mem.recall(agent=agent, role=role, last_n=last_n)
    return {
        "summary": mem.summary(),
        "entries": [
            {"timestamp": e.timestamp.isoformat(), "agent": e.agent,
             "role": e.role, "content": e.content, "tags": e.tags}
            for e in entries
        ],
    }


def _serialize_run(run) -> dict:
    return {
        "run_id": run.run_id,
        "agent": run.agent_name,
        "goal": run.goal,
        "status": run.status,
        "llm_powered": run.llm_powered,
        "duration_ms": round(run.duration_ms, 1),
        "tool_calls_made": run.tool_calls_made,
        "final_answer": run.final_answer,
        "trace": [
            {"step": s.step, "role": s.role, "content": s.content,
             "timestamp": s.timestamp.isoformat()}
            for s in run.steps
        ],
    }
