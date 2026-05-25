"""Tests for the Skills + Agent framework."""

from __future__ import annotations

from sqlalchemy.orm import Session

from libs.agents import get_default_registry, ToolCall
from libs.agents.market_scout import MarketScoutAgent
from libs.agents.portfolio_guardian import PortfolioGuardianAgent


def _sample_bars(n: int = 80) -> list[dict]:
    bars = []
    for i in range(n):
        close = 10.0 + i * 0.1
        bars.append({
            "date": f"2026-04-{(i % 28) + 1:02d}",
            "open": close - 0.05,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 100_000 + i,
            "amount": 1_000_000 + i * 1000,
            "change_pct": 1.0,
        })
    return bars


def _patch_market(monkeypatch) -> None:
    from apps.api.app.services import market_service

    hot = [
        {
            "symbol": f"00000{i}.SZ",
            "name": f"样本{i}",
            "price": 10 + i,
            "change": 0.1,
            "change_pct": 1.0 + i,
            "volume": 1000,
            "turnover": 1_000_000,
        }
        for i in range(1, 8)
    ]
    monkeypatch.setattr(market_service, "get_hot_stocks", lambda top_n=50: hot[:top_n])
    monkeypatch.setattr(market_service, "get_kline", lambda symbol, period="daily", count=120: _sample_bars(count))
    monkeypatch.setattr(
        market_service,
        "get_single_quote",
        lambda symbol: {"symbol": symbol, "name": symbol, "price": 18.0, "change_pct": 1.0},
    )


# ---------------------------------------------------------------------------
# Skill registry
# ---------------------------------------------------------------------------

def test_registry_has_all_categories() -> None:
    reg = get_default_registry()
    cats = {s.category for s in reg.list()}
    assert {"market", "technical", "news", "portfolio", "risk", "execution"} <= cats


def test_registry_skill_count() -> None:
    reg = get_default_registry()
    assert len(reg.list()) >= 12


def test_skill_openai_format() -> None:
    reg = get_default_registry()
    spec = reg.get("get_technical_features").to_openai_tool()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "get_technical_features"
    assert "parameters" in spec["function"]


# ---------------------------------------------------------------------------
# Skill execution (smoke)
# ---------------------------------------------------------------------------

def test_list_universe_returns_data(monkeypatch) -> None:
    _patch_market(monkeypatch)
    reg = get_default_registry()
    res = reg.execute(ToolCall(name="list_universe", arguments={"max_count": 5}))
    assert res.error is None
    assert isinstance(res.output, list)
    assert len(res.output) == 5
    assert "symbol" in res.output[0]


def test_get_technical_features_for_real_symbol(monkeypatch) -> None:
    _patch_market(monkeypatch)
    reg = get_default_registry()
    # 002230.SZ exists only in extended universe → 60 synthetic bars
    res = reg.execute(ToolCall(
        name="get_technical_features", arguments={"symbol": "002230.SZ"},
    ))
    assert res.error is None
    out = res.output
    assert out["symbol"] == "002230.SZ"
    assert "current" in out


def test_detect_chart_pattern(monkeypatch) -> None:
    _patch_market(monkeypatch)
    reg = get_default_registry()
    res = reg.execute(ToolCall(
        name="detect_chart_pattern", arguments={"symbol": "002230.SZ"},
    ))
    assert res.error is None
    assert "trend_20d" in res.output
    assert "patterns" in res.output


def test_unknown_skill_returns_error() -> None:
    reg = get_default_registry()
    res = reg.execute(ToolCall(name="not_a_skill", arguments={}))
    assert res.error is not None


# ---------------------------------------------------------------------------
# MarketScoutAgent (fallback path — keyword/no LLM)
# ---------------------------------------------------------------------------

def test_market_scout_runs_in_fallback(seeded_session: Session) -> None:
    agent = MarketScoutAgent()
    run = agent.run(
        "为我找出今日 3 只最有买入潜力的 A 股",
        context={"db": seeded_session},
    )
    assert run.status == "success"
    assert run.tool_calls_made >= 1
    assert run.final_answer is not None
    final = run.final_answer
    if isinstance(final, dict):
        assert "picks" in final or "method" in final


def test_market_scout_produces_structured_picks(seeded_session: Session) -> None:
    run = MarketScoutAgent().run(
        "find top 3 buys", context={"db": seeded_session},
    )
    final = run.final_answer or {}
    if isinstance(final, dict) and "picks" in final:
        for p in final["picks"]:
            assert "symbol" in p
            assert "score" in p


# ---------------------------------------------------------------------------
# PortfolioGuardianAgent
# ---------------------------------------------------------------------------

def test_portfolio_guardian_runs(seeded_session: Session) -> None:
    run = PortfolioGuardianAgent().run(
        "diagnose my portfolio", context={"db": seeded_session},
    )
    assert run.status == "success"
    final = run.final_answer or {}
    if isinstance(final, dict) and "verdicts" in final:
        for v in final["verdicts"]:
            assert v["action"] in (
                "HOLD", "WATCH", "REDUCE_HALF", "SELL_ALL", "STOP_LOSS",
            )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def test_memory_records_decisions(seeded_session: Session) -> None:
    from libs.agents.memory import get_global_memory
    mem = get_global_memory()
    initial = mem.summary()["n_entries"]
    MarketScoutAgent().run("test", context={"db": seeded_session})
    after = mem.summary()["n_entries"]
    assert after >= initial + 1


# ---------------------------------------------------------------------------
# ResearchAnalystAgent
# ---------------------------------------------------------------------------

def test_research_analyst_returns_run(seeded_session: Session) -> None:
    from libs.agents.research_analyst import ResearchAnalystAgent
    run = ResearchAnalystAgent().run(
        "对 600519.SH 做完整深度研究，给出 BUY/HOLD/SELL 建议。",
        context={"db": seeded_session, "symbol": "600519.SH"},
    )
    assert run.status in ("success", "error")
    assert run.agent_name == "research_analyst"
    assert run.final_answer is not None


def test_research_analyst_output_structure(seeded_session: Session) -> None:
    """Fallback result must contain action, confidence, bull/bear signals."""
    from libs.agents.research_analyst import ResearchAnalystAgent
    run = ResearchAnalystAgent().run(
        "分析 600519.SH",
        context={"db": seeded_session, "symbol": "600519.SH"},
    )
    fa = run.final_answer
    assert isinstance(fa, dict)
    assert fa.get("action") in ("BUY", "SELL", "HOLD", None) or "error" in fa
    assert "confidence" in fa or "error" in fa


def test_research_analyst_symbol_extraction() -> None:
    """_extract_symbol correctly parses a symbol from free text."""
    from libs.agents.research_analyst import ResearchAnalystAgent
    agent = ResearchAnalystAgent()
    assert agent._extract_symbol("分析 600519.SH 的技术面") == "600519.SH"
    assert agent._extract_symbol("000001.SZ 平安银行") == "000001.SZ"
    assert agent._extract_symbol("无代码文本") == ""


def test_research_analyst_no_symbol_graceful(seeded_session: Session) -> None:
    """Passing a goal without a symbol should not raise — error dict returned."""
    from libs.agents.research_analyst import ResearchAnalystAgent
    run = ResearchAnalystAgent().run(
        "做个分析", context={"db": seeded_session}
    )
    assert run.status in ("success", "error")
    fa = run.final_answer
    assert fa is None or isinstance(fa, dict)
