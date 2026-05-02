"""Tests for ProfitMaximizerAgent — the unified buy+sell decision agent."""

from __future__ import annotations

from sqlalchemy.orm import Session

from libs.agents.profit_maximizer import ProfitMaximizerAgent


# ---------------------------------------------------------------------------
# Smoke / structure tests against seeded mock DB
# ---------------------------------------------------------------------------

def test_profit_maximizer_runs_successfully(seeded_session: Session):
    run = ProfitMaximizerAgent().run(
        "今日作战计划",
        context={"db": seeded_session},
    )
    assert run.status == "success"
    assert run.agent_name == "profit_maximizer"


def test_profit_maximizer_returns_unified_action_plan(seeded_session: Session):
    run = ProfitMaximizerAgent().run(
        "今日作战计划",
        context={"db": seeded_session},
    )
    fa = run.final_answer
    assert isinstance(fa, dict)
    # Required output keys per agent contract
    for key in (
        "buy_actions", "sell_actions", "watch_list", "hold_list",
        "cash_pct", "cash_to_deploy", "expected_portfolio_alpha", "summary",
    ):
        assert key in fa, f"missing key {key} in profit-maximizer output"


def test_profit_maximizer_buy_actions_have_required_fields(seeded_session: Session):
    run = ProfitMaximizerAgent().run("plan", context={"db": seeded_session})
    fa = run.final_answer or {}
    for buy in fa.get("buy_actions", []):
        assert "symbol" in buy
        assert "predicted_return" in buy
        assert "horizon" in buy
        assert "suggested_weight" in buy
        assert "reason" in buy
        assert isinstance(buy["predicted_return"], float)
        # Predicted return threshold respected
        assert buy["predicted_return"] >= ProfitMaximizerAgent.MIN_PREDICTED_RETURN


def test_profit_maximizer_sell_actions_categorized(seeded_session: Session):
    """Sell actions must be SELL_ALL or REDUCE_HALF, with urgency tag."""
    run = ProfitMaximizerAgent().run("plan", context={"db": seeded_session})
    fa = run.final_answer or {}
    for sell in fa.get("sell_actions", []):
        assert sell["action"] in ("SELL_ALL", "REDUCE_HALF")
        assert sell["urgency"] in ("high", "medium")
        assert "reason" in sell
        assert "current_pnl" in sell


def test_profit_maximizer_summary_is_human_readable(seeded_session: Session):
    run = ProfitMaximizerAgent().run("plan", context={"db": seeded_session})
    fa = run.final_answer or {}
    summary = fa.get("summary", "")
    assert isinstance(summary, str) and len(summary) > 0


def test_profit_maximizer_no_self_concentration(seeded_session: Session):
    """Buy candidates must not include already-held symbols."""
    run = ProfitMaximizerAgent().run("plan", context={"db": seeded_session})
    fa = run.final_answer or {}
    held = set(fa.get("hold_list", []))
    sells = {s["symbol"] for s in fa.get("sell_actions", [])}
    held_or_selling = held | sells
    for buy in fa.get("buy_actions", []):
        assert buy["symbol"] not in held_or_selling, (
            f"{buy['symbol']} is already held but also in buy list"
        )


def test_profit_maximizer_position_sizing_respects_max_weight(seeded_session: Session):
    run = ProfitMaximizerAgent().run("plan", context={"db": seeded_session})
    fa = run.final_answer or {}
    for buy in fa.get("buy_actions", []):
        assert buy["suggested_weight"] <= ProfitMaximizerAgent.MAX_SINGLE_WEIGHT + 1e-9


def test_profit_maximizer_quantity_is_lot_size_100(seeded_session: Session):
    """A股 must trade in 100-share lots."""
    run = ProfitMaximizerAgent().run("plan", context={"db": seeded_session})
    fa = run.final_answer or {}
    for buy in fa.get("buy_actions", []):
        if "suggested_quantity" in buy:
            assert buy["suggested_quantity"] % 100 == 0


def test_profit_maximizer_expected_alpha_is_sum_of_weighted_returns(seeded_session: Session):
    run = ProfitMaximizerAgent().run("plan", context={"db": seeded_session})
    fa = run.final_answer or {}
    expected = sum(
        b["suggested_weight"] * b["predicted_return"]
        for b in fa.get("buy_actions", [])
    )
    assert abs(fa.get("expected_portfolio_alpha", 0) - expected) < 1e-3


def test_profit_maximizer_records_to_episodic_memory(seeded_session: Session):
    from libs.agents.memory import get_global_memory
    mem = get_global_memory()
    before = len(mem.recall(last_n=500))
    ProfitMaximizerAgent().run("plan", context={"db": seeded_session})
    after = len(mem.recall(last_n=500))
    assert after >= before + 1


def test_profit_maximizer_allowed_tools_complete():
    """Sanity check: agent declares all required tool categories."""
    agent = ProfitMaximizerAgent()
    tools = set(agent.tools())
    # Must cover all 6 skill categories
    assert "list_universe" in tools
    assert "get_technical_features" in tools
    assert "analyze_news_sentiment" in tools
    assert "get_portfolio_overview" in tools
    assert "evaluate_proposed_order" in tools
    assert "preview_order" in tools
    assert "record_recommendation" in tools


# ---------------------------------------------------------------------------
# LLM markdown → structured-JSON parser tests
# ---------------------------------------------------------------------------

_SAMPLE_LLM_REPLY = """## 📊 作战计划

### 🟢 进攻线
- 002230 科大讯飞: RSI 健康, 突破 20 日高
- 002594 比亚迪: 趋势向上

### 🔴 防守线
- 600519 茅台权重 54% 超风控

```json
{
  "summary": "REDUCE 茅台 + BUY 科大讯飞 / 比亚迪",
  "buy_actions": [
    {"symbol": "002230.SZ", "name": "科大讯飞", "predicted_return": 0.05,
     "horizon": "5-20d", "suggested_weight": 0.10, "suggested_quantity": 1500,
     "reason": "RSI 45 / 突破 20 日高"},
    {"symbol": "002594.SZ", "name": "比亚迪", "predicted_return": 0.04,
     "horizon": "5-20d", "suggested_weight": 0.08, "suggested_quantity": 200,
     "reason": "趋势向上"}
  ],
  "sell_actions": [
    {"symbol": "600519.SH", "action": "REDUCE_HALF", "urgency": "medium",
     "current_pnl": 0.047, "reason": "权重 54% 超风控 30%"}
  ],
  "watch_list": [
    {"symbol": "000858.SZ", "warning": "approaching_resistance", "reason": "RSI 73.6"}
  ],
  "hold_list": ["000001.SZ"],
  "cash_to_deploy_pct": 0.30,
  "expected_portfolio_alpha": 0.025
}
```
"""


def test_parse_llm_final_extracts_structured_block():
    agent = ProfitMaximizerAgent()
    result = agent._parse_llm_final(_SAMPLE_LLM_REPLY)
    assert isinstance(result, dict)
    assert result["method"] == "llm_structured"
    assert result["summary"].startswith("REDUCE")
    assert len(result["buy_actions"]) == 2
    assert result["buy_actions"][0]["symbol"] == "002230.SZ"
    assert len(result["sell_actions"]) == 1
    assert result["sell_actions"][0]["action"] == "REDUCE_HALF"
    assert len(result["watch_list"]) == 1
    assert result["hold_list"] == ["000001.SZ"]
    assert result["cash_to_deploy_pct"] == 0.30
    assert result["expected_portfolio_alpha"] == 0.025


def test_parse_llm_final_preserves_markdown_narrative():
    agent = ProfitMaximizerAgent()
    result = agent._parse_llm_final(_SAMPLE_LLM_REPLY)
    md = result["markdown_report"]
    assert "### 🟢 进攻线" in md
    assert "### 🔴 防守线" in md
    # JSON block stripped from the rendered markdown
    assert "```json" not in md


def test_parse_llm_final_returns_none_when_no_json():
    agent = ProfitMaximizerAgent()
    result = agent._parse_llm_final("没有 JSON 的纯文本回答")
    assert result is None


def test_parse_llm_final_returns_none_on_invalid_json():
    agent = ProfitMaximizerAgent()
    result = agent._parse_llm_final("分析\n```json\n{invalid: json}\n```")
    assert result is None


def test_parse_llm_final_picks_last_json_block():
    """If LLM includes example JSON earlier in its prose, pick the LAST."""
    agent = ProfitMaximizerAgent()
    text = """例如可以输出 ```json
{"summary": "示例", "buy_actions": []}
``` 但实际计划是 ```json
{"summary": "真实计划", "buy_actions": [{"symbol":"X.SH","predicted_return":0.05}]}
```"""
    result = agent._parse_llm_final(text)
    assert result is not None
    assert result["summary"] == "真实计划"
    assert result["buy_actions"][0]["symbol"] == "X.SH"


def test_parse_llm_final_defaults_missing_lists():
    """LLM may omit lists; parser must fill empty defaults."""
    agent = ProfitMaximizerAgent()
    text = '总结。\n```json\n{"summary": "仅有持有"}\n```'
    result = agent._parse_llm_final(text)
    assert result["buy_actions"] == []
    assert result["sell_actions"] == []
    assert result["watch_list"] == []
    assert result["hold_list"] == []
