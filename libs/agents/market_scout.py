"""MarketScoutAgent — autonomous market opportunity hunter.

Goal: find the most attractive BUY candidates across the universe.

When LLM-powered:
    The agent receives the system prompt below and ~13 tools.
    It chooses dynamically whether to call list_universe → loop through
    candidates → fetch features → fetch news → eventually record_recommendation.

When LLM is not configured:
    The fallback runs a deterministic plan that mirrors what a human
    would do: list a slice of the universe, fetch technical features for
    each, score them, and short-list top-N. Identical inputs produce
    identical outputs.
"""

from __future__ import annotations

from libs.agents.base_agent import BaseAgent
from libs.agents.skills import ToolCall


_SYSTEM = """你是一名 A 股量化研究员。目标：基于实时数据找出当下最有买入潜力的股票。

工作流程：
1. 使用 list_universe 列出可投资股票池。
2. 用 get_technical_features / detect_chart_pattern 评估候选标的的技术面。
3. 必要时用 analyze_news_sentiment 检查相关舆情风险。
4. 用 calc_concentration 检查组合是否已重仓相关行业。
5. 用 preview_order 验证拟下订单是否会被风控/A 股规则拦截。
6. 调用 record_recommendation 写入正式建议。

要求：
- 多步推理，每步先思考再决定调用哪个工具。
- 最终给出 1~5 只股票的明确建议（BUY/HOLD），含理由、置信度（0~1）、风险标记。
- 不要凭空捏造数据，所有结论必须基于工具返回的真实数值。
- 排除 ST、退市风险、连续涨停的标的。
"""


class MarketScoutAgent(BaseAgent):
    name = "market_scout"
    max_steps = 8

    # Tools this agent is allowed to call
    _ALLOWED = [
        "list_universe",
        "get_realtime_quote",
        "get_daily_bars",
        "get_technical_features",
        "detect_chart_pattern",
        "get_support_resistance",
        "search_news",
        "analyze_news_sentiment",
        "get_portfolio_overview",
        "calc_concentration",
        "preview_order",
        "record_recommendation",
    ]

    def system_prompt(self) -> str:
        return _SYSTEM

    def tools(self) -> list[str]:
        return self._ALLOWED

    # ------------------------------------------------------------------
    # Fallback plan
    # ------------------------------------------------------------------

    def _fallback_plan(self, goal: str, context: dict) -> list[ToolCall]:
        # 1) Probe the universe — the orchestrator will use the response
        #    to chain follow-up tool calls. In strict fallback we just
        #    use a fixed top-15 sample.
        return [ToolCall(name="list_universe", arguments={"max_count": 15, "exclude_st": True})]

    def _summarize_observations(self, goal: str, observations) -> dict:
        """Two-phase fallback: list_universe → score each → pick top 3."""
        from libs.agents.skills import ToolCall
        from libs.agents.skills import get_default_registry

        if not observations or observations[0].error:
            return {"error": "list_universe failed", "picks": []}

        registry = get_default_registry()
        universe = observations[0].output or []
        candidates: list[dict] = []
        for entry in universe[:15]:
            symbol = entry["symbol"]
            feat = registry.execute(
                ToolCall(name="get_technical_features", arguments={"symbol": symbol})
            )
            patt = registry.execute(
                ToolCall(name="detect_chart_pattern", arguments={"symbol": symbol})
            )
            if feat.error or patt.error:
                continue
            f = feat.output or {}
            p = patt.output or {}
            momentum = (f.get("return_5d") or 0) * 0.5 + (f.get("return_20d") or 0) * 0.3
            # Defensive against None values
            trend_bonus = 0.05 if p.get("above_ma20") else -0.05
            patterns = [pp.get("name") for pp in (p.get("patterns") or [])]
            golden = 0.05 if "golden_cross" in patterns else 0
            breakout = 0.04 if "breakout_high" in patterns else 0
            volume_surge = 0.03 if "volume_surge" in patterns else 0
            volatility = f.get("volatility_20d") or 0.02
            score = (
                momentum + trend_bonus + golden + breakout + volume_surge
                - max(0, volatility - 0.025) * 5
            )
            candidates.append({
                "symbol": symbol,
                "name": entry["name"],
                "industry": entry["industry"],
                "score": round(score, 4),
                "patterns": patterns,
                "trend_20d": p.get("trend_20d"),
                "rsi_14d": f.get("rsi_14d"),
                "current_close": f.get("current_close"),
                "return_5d": f.get("return_5d"),
                "return_20d": f.get("return_20d"),
            })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        top_picks = candidates[:3]
        return {
            "method": "fallback_deterministic",
            "n_evaluated": len(candidates),
            "picks": top_picks,
            "explanation": (
                f"无 LLM 模式下，扫描 {len(candidates)} 只股票，按动量+趋势+形态打分，"
                f"取得分前 3。建议 BUY: " + ", ".join([f"{p['symbol']}({p['name']})" for p in top_picks])
                if top_picks else "未找到合适标的"
            ),
        }
