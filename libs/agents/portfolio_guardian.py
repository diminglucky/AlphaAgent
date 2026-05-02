"""PortfolioGuardianAgent — autonomous holdings doctor.

Goal: scan all held positions and decide for each whether action is
needed (HOLD / REDUCE / SELL_ALL), with reasoning grounded in tools.

When LLM-powered:
    Iterates positions, asking targeted questions per holding, and
    decides actions dynamically.

Fallback path: deterministic per-position diagnostic that mirrors
PositionMonitor's rules but produces structured agent-style output
with citations to specific tool outputs.
"""

from __future__ import annotations

from libs.agents.base_agent import BaseAgent
from libs.agents.skills import ToolCall


_SYSTEM = """你是一名 A 股组合风控官。**目标：在风险发生之前、利润最大化之时主动调整仓位**，而不是事后止损。

可用工具：
- get_portfolio_overview / check_position_health（看持仓基本面）
- get_technical_features / detect_chart_pattern / get_support_resistance（看技术面）
- analyze_news_sentiment（看舆情）
- preview_order / record_recommendation

判断分四级：
- **HOLD** 持有不动
- **WATCH** 早期预警，加密观察（不操作但关注）
- **REDUCE_HALF** 减半仓锁利润 / 降风险
- **SELL_ALL** 清仓

**前瞻性预警优先于反应性止损**——下面任意 1 条触发就考虑 WATCH 或 REDUCE：

A. 顶部预警（在亏钱之前）：
   1. RSI 顶背离：价格新高但 RSI 走弱 → 动能衰竭
   2. MACD 柱连续 3 日萎缩 → 死叉将至
   3. 量价背离：价格新高但量能萎缩 → 上涨乏力
   4. 触及阻力位 + RSI > 65 → 大概率受阻
   5. 高位窄幅滞涨 → 筹码派发

B. 利润保护（让赚的钱留下来）：
   6. 浮盈 ≥ +15%：启动 trailing stop，从最高点回撤 ≥5% → REDUCE_HALF
   7. 浮盈 ≥ +25%：主动 REDUCE_HALF 锁定一半
   8. 距阻力位 < 3% 且 浮盈 ≥ +10% → REDUCE_HALF

C. 反应性兜底（最后底线）：
   9. 浮亏 ≤ -8% → SELL_ALL
   10. 死叉/破位/重大利空 → REDUCE 或 SELL
"""


class PortfolioGuardianAgent(BaseAgent):
    name = "portfolio_guardian"
    max_steps = 12

    _ALLOWED = [
        "get_portfolio_overview",
        "check_position_health",
        "get_technical_features",
        "detect_chart_pattern",
        "get_support_resistance",
        "analyze_news_sentiment",
        "preview_order",
        "record_recommendation",
        "calc_concentration",
    ]

    def system_prompt(self) -> str:
        return _SYSTEM

    def tools(self) -> list[str]:
        return self._ALLOWED

    # ------------------------------------------------------------------
    # Fallback (deterministic)
    # ------------------------------------------------------------------

    def _fallback_plan(self, goal: str, context: dict) -> list[ToolCall]:
        return [ToolCall(name="get_portfolio_overview", arguments={})]

    def _summarize_observations(self, goal: str, observations) -> dict:
        from libs.agents.skills import ToolCall
        from libs.agents.skills import get_default_registry

        if not observations or observations[0].error:
            return {"error": "get_portfolio_overview failed", "verdicts": []}

        reg = get_default_registry()
        # Need to forward `_db` from caller's context — only available via run() ctx.
        # Since fallback runs without live ctx here, we re-execute via the same
        # registry which has the session injected by the run context.
        # In practice this is invoked via run(goal, context={"db": session}).
        # The registry.execute will receive context via `execute()` again.
        ctx = self._captured_ctx
        port = observations[0].output or {}
        positions = port.get("positions", [])
        verdicts = []
        for pos in positions:
            symbol = pos["symbol"]
            health = reg.execute(
                ToolCall(name="check_position_health", arguments={"symbol": symbol}),
                context=ctx,
            )
            patt = reg.execute(
                ToolCall(name="detect_chart_pattern", arguments={"symbol": symbol}),
                context=ctx,
            )
            news = reg.execute(
                ToolCall(name="analyze_news_sentiment", arguments={"symbol": symbol, "days": 7}),
                context=ctx,
            )
            if health.error:
                continue

            h = health.output or {}
            p = patt.output or {}
            n = news.output or {}
            pnl = h.get("pnl_pct", 0)
            dd = h.get("drawdown_from_peak", 0)
            pattern_objs = p.get("patterns") or []
            patterns = [pp.get("name") for pp in pattern_objs]
            warning_patterns = [pp for pp in pattern_objs if pp.get("severity") == "warning"]
            avg_sent = n.get("avg_sentiment", 0) if not n.get("error") else 0
            n_neg = n.get("negative_events_count", 0) if not n.get("error") else 0
            rsi = p.get("rsi_14d")

            # ========== Proactive verdict logic ==========
            # Priorities (highest first):
            #   C9. -8% stop loss (hard floor)
            #   C10. confirmed death cross / breakdown / heavy news loss
            #   B6/B7. profit protection (trailing stop / take half profit)
            #   A1-A5. predictive top warnings (severity="warning" patterns)
            #   B8. close to resistance with profit
            #   default HOLD

            action = "HOLD"
            severity_score = 0  # 0=hold, 1=watch, 2=reduce, 3=sell
            reasons: list[str] = []

            def _set(level: int, new_action: str, why: str) -> None:
                nonlocal action, severity_score
                reasons.append(why)
                if level > severity_score:
                    severity_score = level
                    action = new_action

            # ----- C: reactive hard floor -----
            if pnl <= -0.08:
                _set(3, "SELL_ALL", f"⛔ 浮亏 {pnl*100:.1f}% 已触发 -8% 止损线")
            if "death_cross" in patterns:
                _set(2, "REDUCE_HALF", "🔻 已确认 MA5 死叉 MA20")
            if "breakdown_low" in patterns:
                _set(2, "REDUCE_HALF", "🔻 已跌破 20 日低点")
            if avg_sent <= -0.3 and n_neg >= 2:
                _set(2, "REDUCE_HALF", f"📰 近 7 日累计 {n_neg} 条重大负面新闻")

            # ----- B: profit protection -----
            if pnl >= 0.25:
                _set(2, "REDUCE_HALF", f"💰 浮盈 {pnl*100:.1f}% ≥ +25%，主动止盈一半")
            elif pnl >= 0.15 and dd <= -0.05:
                _set(2, "REDUCE_HALF", (
                    f"💰 浮盈 {pnl*100:.1f}% 触发 trailing stop "
                    f"（从最高点回撤 {dd*100:.1f}%）"
                ))

            # ----- A: predictive top warnings (fires BEFORE the loss) -----
            if warning_patterns:
                names = [w["name"] for w in warning_patterns]
                # Two or more concurrent warnings → REDUCE preemptively
                if len(warning_patterns) >= 2:
                    _set(2, "REDUCE_HALF", (
                        f"⚠️ 同时出现 {len(warning_patterns)} 个顶部信号 "
                        f"({', '.join(names)}) — 提前减仓避险"
                    ))
                # If holding a profit + 1 warning → also REDUCE to lock gains
                elif pnl >= 0.10 and len(warning_patterns) >= 1:
                    pat = warning_patterns[0]
                    _set(2, "REDUCE_HALF", (
                        f"⚠️ 浮盈 {pnl*100:.1f}% + 顶部预警 "
                        f"({pat['name']}: {pat.get('desc','')}) — 落袋为安一半"
                    ))
                # Single warning, no profit → just WATCH
                else:
                    pat = warning_patterns[0]
                    _set(1, "WATCH", (
                        f"👀 早期预警: {pat['name']} — {pat.get('desc','')}"
                    ))

            # ----- B8: approaching resistance with material profit -----
            if pnl >= 0.10 and "approaching_resistance" in patterns and severity_score < 2:
                _set(2, "REDUCE_HALF", f"📍 浮盈 {pnl*100:.1f}% 同时距阻力位 < 2% — 锁定半仓")

            # ----- C: other late-stage drawdown -----
            if dd <= -0.15 and severity_score < 2:
                _set(2, "REDUCE_HALF", f"🔻 自高点回撤 {dd*100:.1f}%")

            verdicts.append({
                "symbol": symbol,
                "action": action,
                "pnl_pct": pnl,
                "drawdown": dd,
                "patterns": patterns,
                "warning_patterns": [w["name"] for w in warning_patterns],
                "rsi_14d": rsi,
                "avg_sentiment": avg_sent,
                "reasons": reasons or ["持仓健康，继续持有"],
            })

        actionable = [v for v in verdicts if v["action"] not in ("HOLD",)]
        watch = [v for v in verdicts if v["action"] == "WATCH"]
        reduce_ = [v for v in verdicts if v["action"] == "REDUCE_HALF"]
        sell = [v for v in verdicts if v["action"] == "SELL_ALL"]

        if not actionable:
            summary = f"✅ 全部 {len(positions)} 只持仓健康"
        else:
            parts = []
            if sell:
                parts.append(f"🔴 SELL {len(sell)} 只 ({', '.join(v['symbol'] for v in sell)})")
            if reduce_:
                parts.append(f"🟡 REDUCE {len(reduce_)} 只 ({', '.join(v['symbol'] for v in reduce_)})")
            if watch:
                parts.append(f"⚠️ WATCH {len(watch)} 只 ({', '.join(v['symbol'] for v in watch)})")
            summary = f"扫描 {len(positions)} 只持仓 — " + " | ".join(parts)

        return {
            "method": "fallback_deterministic",
            "n_positions": len(positions),
            "verdicts": verdicts,
            "actions_required": len([v for v in verdicts if v["action"] in ("REDUCE_HALF", "SELL_ALL")]),
            "watch_count": len(watch),
            "reduce_count": len(reduce_),
            "sell_count": len(sell),
            "summary": summary,
        }

    # capture ctx at run time (BaseAgent.run sets this before calling fallback)
    _captured_ctx: dict = {}

    def run(self, goal, context=None):
        self._captured_ctx = context or {}
        return super().run(goal, context)
