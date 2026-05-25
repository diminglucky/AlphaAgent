"""ProfitMaximizerAgent — 一体化利益最大化决策代理.

Goal: produce a SINGLE concrete action plan that says
  - "买这几只" (with sizing + predicted upside + horizon)
  - "卖这几只" (with reason + immediacy)
  - "观察这几只" (early warning, no trade yet)
  - "保留这几只" (healthy holds)

It internally orchestrates two phases:
1. **OPPORTUNITY**: scan universe → score → pick top-N where predicted
   upside > threshold and risk is acceptable.
2. **DEFENSE**: diagnose every existing position with the proactive
   Guardian rules (top-warnings, trailing stop, hard floor).

Then it reconciles the two against current cash, single-name limits and
sector concentration to produce a final action list that respects
portfolio constraints.

When LLM is configured (QUANT_LLM_PROVIDER != keyword), the BaseAgent
ReAct loop drives the same skills via function-calling. When not, the
deterministic fallback below produces identical structured output.
"""

from __future__ import annotations

from libs.agents.base_agent import BaseAgent
from libs.agents.skills import ToolCall


_SYSTEM = """你是「利益最大化代理」(ProfitMaximizer)，是 A 股交易系统的最终决策官。

**核心目标**：在风险可控前提下，让用户的资金组合长期收益最大化。

**两线作战**：
A. 进攻线 — 主动捕捉上涨机会
   1. list_universe 扫描股票池
   2. 对每只候选用 get_technical_features + detect_chart_pattern
      看动量、趋势、形态，评估「未来 5-20 日预期收益」
   3. 必要时用 analyze_news_sentiment 排除有重大利空的
   4. 用 calc_concentration 避免行业过度集中
   5. 用 preview_order 验证不会触发风控/涨停板买不进/资金不足
   6. 给出 1~3 只买入建议，每只含 predicted_return（百分比）+ 仓位建议

B. 防守线 — 提前规避下跌风险
   1. get_portfolio_overview 拿当前持仓
   2. 对每只持仓 check_position_health + detect_chart_pattern
   3. **预警优先**：发现 RSI 顶背离 / MACD 萎缩 / 量价背离 / 触及阻力
      / 高位滞涨 任意 1 条 → 至少 WATCH；2 条以上或持有浮盈 ≥10% → REDUCE
   4. **利润保护**：浮盈 ≥15% + 回撤 5% → trailing stop REDUCE；
      浮盈 ≥25% → REDUCE 锁一半
   5. **底线**：浮亏 -8% 必清仓

**最终输出格式（必须严格遵守）**：先用 Markdown 给出详细作战分析（含理由、形态、风险点），
**然后在最后单独追加一个 ```json 代码块**，块内为以下结构（便于 UI 直接消费）：

```json
{
  "summary": "一句话作战概述",
  "buy_actions":  [
    {"symbol": "002230.SZ", "name": "科大讯飞", "predicted_return": 0.05,
     "horizon": "5-20d", "suggested_weight": 0.10, "suggested_quantity": 1500,
     "reason": "RSI 45 健康 / 突破 20 日高 / MACD 正柱"}
  ],
  "sell_actions": [
    {"symbol": "600519.SH", "action": "REDUCE_HALF", "urgency": "medium",
     "current_pnl": 0.047, "reason": "权重 54% 超风控上限 30%"}
  ],
  "watch_list":   [
    {"symbol": "000858.SZ", "warning": "approaching_resistance",
     "reason": "RSI 73.6 偏高 / 距阻力 0.16%"}
  ],
  "hold_list":    ["000001.SZ"],
  "cash_to_deploy_pct": 0.30,
  "expected_portfolio_alpha": 0.025
}
```

**底线约束**：
- 单票最大权重 10%（参考风控）
- 现金低于 20% 时，优先减仓再加仓
- 任何 SELL_ALL 都必须先经 preview_order 验证
- 决策必须可解释，每个动作给出量化依据
"""


class ProfitMaximizerAgent(BaseAgent):
    name = "profit_maximizer"
    max_steps = 16

    _ALLOWED = [
        # Universe + market data
        "list_universe",
        "get_realtime_quote",
        "get_daily_bars",
        # Technical
        "get_technical_features",
        "detect_chart_pattern",
        "get_support_resistance",
        # News
        "search_news",
        "analyze_news_sentiment",
        # Portfolio
        "get_portfolio_overview",
        "check_position_health",
        "calc_concentration",
        # Risk + execution
        "list_risk_rules",
        "evaluate_proposed_order",
        "check_a_share_rules",
        "preview_order",
        "record_recommendation",
    ]

    # Hyperparams (could be moved to env later)
    UNIVERSE_SAMPLE = 15
    TOP_N_BUY = 3
    MAX_SINGLE_WEIGHT = 0.10
    MIN_CASH_BUFFER_PCT = 0.20
    MIN_PREDICTED_RETURN = 0.02   # don't buy if expected upside < 2%

    def system_prompt(self) -> str:
        return _SYSTEM

    def tools(self) -> list[str]:
        return self._ALLOWED

    # ------------------------------------------------------------------
    # LLM-mode post-processing
    # ------------------------------------------------------------------

    def _parse_llm_final(self, content):
        """Extract the trailing ```json``` block emitted by the LLM and
        merge it with the raw markdown narrative.

        Returns a dict combining:
            - structured fields (buy_actions / sell_actions / ...)
            - markdown_report  : original markdown text for UI rendering
            - summary          : either from JSON or first non-empty line

        Returns None if parsing fails so BaseAgent keeps the raw string.
        """
        import json
        import re

        if not isinstance(content, str) or not content.strip():
            return None

        # Greedy on the LAST fenced json block — LLM may include earlier
        # code samples in its analysis.
        matches = re.findall(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if not matches:
            return None
        try:
            structured = json.loads(matches[-1])
        except json.JSONDecodeError:
            return None
        if not isinstance(structured, dict):
            return None

        # Strip the json block from markdown so UI doesn't render duplicates.
        markdown = re.sub(
            r"```json\s*\{.*?\}\s*```\s*$",
            "",
            content,
            count=1,
            flags=re.DOTALL,
        ).rstrip()

        structured.setdefault("buy_actions", [])
        structured.setdefault("sell_actions", [])
        structured.setdefault("watch_list", [])
        structured.setdefault("hold_list", [])
        structured.setdefault("summary", markdown.strip().split("\n", 1)[0][:200])
        structured["markdown_report"] = markdown
        structured["method"] = "llm_structured"
        return structured

    # ------------------------------------------------------------------
    # Fallback (deterministic) — runs without LLM
    # ------------------------------------------------------------------

    def _fallback_plan(self, goal: str, context: dict) -> list[ToolCall]:
        # The two anchor calls; the summarizer chains many more itself.
        return [
            ToolCall(name="list_universe",
                     arguments={"max_count": self.UNIVERSE_SAMPLE, "exclude_st": True}),
            ToolCall(name="get_portfolio_overview", arguments={}),
        ]

    def _summarize_observations(self, goal: str, observations) -> dict:
        """Run both lines of attack and reconcile into one action plan."""
        from libs.agents.skills import ToolCall, get_default_registry
        from libs.agents.market_scout import MarketScoutAgent
        from libs.agents.portfolio_guardian import PortfolioGuardianAgent

        if len(observations) < 2 or observations[0].error or observations[1].error:
            return {
                "method": "fallback_deterministic",
                "error": "anchor calls failed",
                "buy_actions": [],
                "sell_actions": [],
                "watch_list": [],
                "hold_list": [],
                "n_universe_scanned": 0,
                "n_holdings": 0,
                "cash_pct": 1.0,
                "cash_to_deploy": 0.0,
                "expected_portfolio_alpha": 0.0,
                "sell_first": False,
                "summary": "无法生成计划：基础行情或持仓工具调用失败",
            }

        ctx = self._captured_ctx
        reg = get_default_registry()

        universe = observations[0].output or []
        portfolio = observations[1].output or {}
        port_summary = portfolio.get("summary", {}) or {}
        positions = portfolio.get("positions", []) or []
        held_symbols = {p["symbol"] for p in positions}

        total_asset = port_summary.get("total_asset") or 0
        cash = port_summary.get("cash") or 0
        cash_pct = cash / total_asset if total_asset else 1.0

        # ============================================================
        # PHASE A — OPPORTUNITY (find buys)
        # ============================================================
        scout = MarketScoutAgent()
        # Reuse Scout's deterministic scoring path on the same universe.
        scout_obs = [observations[0]]  # list_universe result
        scout_result = scout._summarize_observations(goal, scout_obs)
        raw_picks = scout_result.get("picks", []) or []

        buy_actions = []
        for pick in raw_picks:
            sym = pick["symbol"]
            if sym in held_symbols:
                continue  # skip already-held to avoid concentration

            # Predicted return: combine 5d momentum, trend strength, pattern bonus
            r5 = float(pick.get("return_5d") or 0)
            r20 = float(pick.get("return_20d") or 0)
            trend = pick.get("trend_20d") or "sideways"
            patterns = pick.get("patterns") or []
            rsi = pick.get("rsi_14d") or 50

            # Heuristic: continuation factor of 5-day momentum, dampened
            # if RSI is already overbought.
            base_predicted = r5 * 0.6 + r20 * 0.2
            if "breakout_high" in patterns or "golden_cross" in patterns:
                base_predicted += 0.02
            if rsi > 75:
                base_predicted *= 0.5  # already overbought, dampen
            elif rsi < 30:
                base_predicted += 0.02  # oversold bounce premium
            if trend == "strong_up":
                base_predicted += 0.01
            elif trend == "strong_down":
                base_predicted -= 0.03

            predicted_return = round(base_predicted, 4)
            if predicted_return < self.MIN_PREDICTED_RETURN:
                continue

            # Confidence — based on score + clarity of signal
            confidence = max(0.30, min(0.85, 0.40 + pick["score"] * 1.5))

            # Concentration check — try to avoid same industry as existing top weight
            conc = reg.execute(
                ToolCall(name="calc_concentration", arguments={}),
                context=ctx,
            )
            industry_warning = ""
            if not conc.error:
                industries = conc.output.get("industry_distribution", []) or []
                same_ind = next(
                    (i for i in industries if i["industry"] == pick.get("industry")),
                    None,
                )
                if same_ind and same_ind["weight"] > 0.30:
                    industry_warning = (
                        f"⚠️ {pick.get('industry')} 板块权重已 {same_ind['weight']*100:.0f}%，"
                        "建议减半仓位"
                    )

            suggested_weight = self.MAX_SINGLE_WEIGHT
            if industry_warning:
                suggested_weight *= 0.5

            reason_parts = [
                f"5日 {r5*100:+.1f}% / 20日 {r20*100:+.1f}%",
                f"RSI={rsi:.0f}",
                f"趋势={trend}",
            ]
            if patterns:
                reason_parts.append(f"形态={'+'.join(patterns)}")
            if industry_warning:
                reason_parts.append(industry_warning)

            buy_actions.append({
                "symbol": sym,
                "name": pick.get("name"),
                "industry": pick.get("industry"),
                "predicted_return": predicted_return,
                "horizon": "5-20 trading days",
                "confidence": round(confidence, 2),
                "suggested_weight": round(suggested_weight, 4),
                "current_close": pick.get("current_close"),
                "reason": " | ".join(reason_parts),
            })

            if len(buy_actions) >= self.TOP_N_BUY:
                break

        # ============================================================
        # PHASE B — DEFENSE (find sells / watches)
        # ============================================================
        guardian = PortfolioGuardianAgent()
        guardian._captured_ctx = ctx
        guardian_result = guardian._summarize_observations(goal, [observations[1]])
        verdicts = guardian_result.get("verdicts", []) or []

        sell_actions = []
        watch_list = []
        hold_list = []
        for v in verdicts:
            entry = {
                "symbol": v["symbol"],
                "current_pnl": round(v.get("pnl_pct", 0), 4),
                "drawdown": round(v.get("drawdown", 0), 4),
                "reason": " ; ".join(v.get("reasons") or []),
            }
            if v["action"] in ("SELL_ALL", "REDUCE_HALF"):
                entry["action"] = v["action"]
                entry["urgency"] = "high" if v["action"] == "SELL_ALL" else "medium"
                sell_actions.append(entry)
            elif v["action"] == "WATCH":
                entry["warning"] = ", ".join(v.get("warning_patterns") or [])
                watch_list.append(entry)
            else:
                hold_list.append(v["symbol"])

        # ============================================================
        # PHASE C — RECONCILE  (cash buffer, ordering, capital allocation)
        # ============================================================
        # If cash buffer < 20% AND there are sells → flag "sell first"
        sell_first = (
            cash_pct < self.MIN_CASH_BUFFER_PCT
            and any(s["action"] == "SELL_ALL" for s in sell_actions)
        )

        # Allocate cash to buys: equal weight, capped by MAX_SINGLE_WEIGHT × total
        cash_to_deploy = 0.0
        if buy_actions and not sell_first:
            per_position = min(
                cash * 0.8 / max(1, len(buy_actions)),  # leave 20% buffer
                self.MAX_SINGLE_WEIGHT * total_asset,
            )
            cash_to_deploy = per_position * len(buy_actions)
            for ba in buy_actions:
                shares = int(per_position / max(ba.get("current_close") or 1, 1))
                # Round to A-share lot of 100
                ba["suggested_quantity"] = (shares // 100) * 100
                ba["suggested_capital"] = ba["suggested_quantity"] * (ba.get("current_close") or 0)

        # Expected portfolio alpha = sum(weight × predicted_return)
        expected_alpha = sum(
            ba["suggested_weight"] * ba["predicted_return"] for ba in buy_actions
        )

        # ============================================================
        # SUMMARY
        # ============================================================
        if not buy_actions and not sell_actions and not watch_list:
            summary = "📊 当前组合健康，无新增操作建议。继续持有。"
        else:
            parts = []
            if sell_actions:
                sells_high = [s["symbol"] for s in sell_actions if s["urgency"] == "high"]
                sells_med = [s["symbol"] for s in sell_actions if s["urgency"] == "medium"]
                if sells_high:
                    parts.append(f"🔴 立即清仓 {len(sells_high)} 只 ({', '.join(sells_high)})")
                if sells_med:
                    parts.append(f"🟡 减半仓 {len(sells_med)} 只 ({', '.join(sells_med)})")
            if watch_list:
                parts.append(
                    f"⚠️ 加密观察 {len(watch_list)} 只 ({', '.join(w['symbol'] for w in watch_list)})"
                )
            if buy_actions:
                buys = ", ".join(
                    f"{ba['symbol']}({ba['predicted_return']*100:+.1f}%)" for ba in buy_actions
                )
                parts.append(f"🟢 买入 {len(buy_actions)} 只 [{buys}]")
            if sell_first:
                parts.insert(0, "⚠️ 现金不足，先卖后买")
            summary = " | ".join(parts)

        return {
            "method": "fallback_deterministic",
            "buy_actions": buy_actions,
            "sell_actions": sell_actions,
            "watch_list": watch_list,
            "hold_list": hold_list,
            "n_universe_scanned": len(universe),
            "n_holdings": len(positions),
            "cash_pct": round(cash_pct, 3),
            "cash_to_deploy": round(cash_to_deploy, 2),
            "expected_portfolio_alpha": round(expected_alpha, 4),
            "sell_first": sell_first,
            "summary": summary,
        }

    # capture ctx at run time
    _captured_ctx: dict = {}

    def run(self, goal, context=None):
        self._captured_ctx = context or {}
        return super().run(goal, context)
