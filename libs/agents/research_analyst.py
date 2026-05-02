"""ResearchAnalystAgent — deep research on a single symbol.

Goal: produce a multi-dimensional analysis (technical / news / risk /
position-context) and an action recommendation with confidence.

This replaces the old multi-agent advisor whose components were hardwired
in services/advisor.py. Now every dimension is a Skill that this agent
chooses to invoke (or skip) per situation.
"""

from __future__ import annotations

from libs.agents.base_agent import BaseAgent
from libs.agents.skills import ToolCall


_SYSTEM = """你是一名 A 股资深证券研究分析师。当用户给你一只股票代码时，你要做完整的深度研究。

可用工具：
- get_realtime_quote / get_daily_bars / get_technical_features / detect_chart_pattern / get_support_resistance
- search_news / analyze_news_sentiment
- get_portfolio_overview / check_position_health / calc_concentration
- evaluate_proposed_order / preview_order
- record_recommendation

工作流程：
1. 先 get_technical_features + detect_chart_pattern 摸清当前技术面
2. analyze_news_sentiment 看是否有重大舆情
3. get_support_resistance 给出止损/止盈参考位
4. 检查用户是否已持仓 (check_position_health)；若已持仓，结合成本、回撤判断
5. 给出明确结论：BUY / HOLD / SELL，含置信度（0~1）、目标价、止损位、关键风险
6. 调 record_recommendation 持久化结论

要求：所有数字必须来自工具返回，禁止臆造。
"""


class ResearchAnalystAgent(BaseAgent):
    name = "research_analyst"
    max_steps = 10

    _ALLOWED = [
        "get_realtime_quote",
        "get_daily_bars",
        "get_technical_features",
        "detect_chart_pattern",
        "get_support_resistance",
        "search_news",
        "analyze_news_sentiment",
        "get_portfolio_overview",
        "check_position_health",
        "calc_concentration",
        "evaluate_proposed_order",
        "preview_order",
        "record_recommendation",
    ]

    def system_prompt(self) -> str:
        return _SYSTEM

    def tools(self) -> list[str]:
        return self._ALLOWED

    # ------------------------------------------------------------------
    # Fallback: deterministic deep-dive
    # ------------------------------------------------------------------

    def _fallback_plan(self, goal: str, context: dict) -> list[ToolCall]:
        symbol = (context or {}).get("symbol") or self._extract_symbol(goal)
        if not symbol:
            return []
        return [
            ToolCall(name="get_technical_features", arguments={"symbol": symbol}),
            ToolCall(name="detect_chart_pattern", arguments={"symbol": symbol}),
            ToolCall(name="get_support_resistance", arguments={"symbol": symbol}),
            ToolCall(name="analyze_news_sentiment", arguments={"symbol": symbol, "days": 7}),
            ToolCall(name="check_position_health", arguments={"symbol": symbol}),
        ]

    def _summarize_observations(self, goal: str, observations) -> dict:
        symbol = self._extract_symbol(goal) or ""
        feat = _get(observations, "get_technical_features")
        pattern = _get(observations, "detect_chart_pattern")
        sr = _get(observations, "get_support_resistance")
        news = _get(observations, "analyze_news_sentiment")
        position = _get(observations, "check_position_health")

        if feat is None:
            return {"error": "no technical data", "symbol": symbol}

        # ---- Technical scoring ----
        ret_5d = feat.get("return_5d") or 0
        ret_20d = feat.get("return_20d") or 0
        rsi = feat.get("rsi_14d")
        ma20 = feat.get("ma_20d") or 0
        close = feat.get("current_close") or 0
        vol_ratio = feat.get("volume_ratio_5d") or 1
        volatility = feat.get("volatility_20d") or 0.02

        patterns = [pp.get("name") for pp in (pattern.get("patterns") or [])] if pattern else []
        trend = pattern.get("trend_20d") if pattern else "unknown"

        # ---- Sentiment scoring ----
        avg_sent = news.get("avg_sentiment") if news and not news.get("error") else 0
        n_neg = news.get("negative_events_count") if news and not news.get("error") else 0

        # ---- Decision logic ----
        bull_signals = []
        bear_signals = []
        if ret_5d > 0.03:
            bull_signals.append(f"5日 +{ret_5d*100:.1f}%")
        elif ret_5d < -0.03:
            bear_signals.append(f"5日 {ret_5d*100:.1f}%")
        if close > ma20 and ma20 > 0:
            bull_signals.append(f"站上 MA20 {((close-ma20)/ma20*100):.1f}%")
        elif ma20 > 0 and close < ma20:
            bear_signals.append(f"跌破 MA20 {((close-ma20)/ma20*100):.1f}%")
        if "golden_cross" in patterns:
            bull_signals.append("MA5 金叉 MA20")
        if "death_cross" in patterns:
            bear_signals.append("MA5 死叉 MA20")
        if "breakout_high" in patterns:
            bull_signals.append("突破 20 日高点")
        if "breakdown_low" in patterns:
            bear_signals.append("跌破 20 日低点")
        if "volume_surge" in patterns and ret_5d > 0:
            bull_signals.append("放量上涨")
        elif "volume_surge" in patterns and ret_5d < 0:
            bear_signals.append("放量下跌")
        if rsi is not None:
            if rsi > 75:
                bear_signals.append(f"RSI {rsi:.0f}（超买）")
            elif rsi < 25:
                bull_signals.append(f"RSI {rsi:.0f}（超卖反弹机会）")
        if avg_sent < -0.3:
            bear_signals.append(f"近期负面情绪（avg={avg_sent:.2f}, neg={n_neg}）")
        elif avg_sent > 0.3:
            bull_signals.append(f"近期正面情绪（avg={avg_sent:.2f}）")

        bull = len(bull_signals)
        bear = len(bear_signals)
        net = bull - bear
        if net >= 2:
            action = "BUY"
            confidence = min(0.85, 0.5 + 0.1 * net)
        elif net <= -2:
            action = "SELL"
            confidence = min(0.85, 0.5 + 0.1 * abs(net))
        else:
            action = "HOLD"
            confidence = 0.5

        # If user already has position, soften BUY (avoid加仓 unless strong)
        held = position and not position.get("error")
        if held:
            pnl_pct = position.get("pnl_pct", 0)
            if action == "BUY" and pnl_pct > 0.10:
                action = "HOLD"  # already profitable, no加仓
                bear_signals.append("已盈利持仓，避免追高")
            if action == "SELL" and pnl_pct < -0.05:
                confidence = min(0.95, confidence + 0.1)  # 强化止损信号

        # Stop / target levels
        support = (sr or {}).get("support_levels") or []
        resistance = (sr or {}).get("resistance_levels") or []
        stop_loss = max(support[-1] if support else 0, close * 0.92) if action == "BUY" else None
        take_profit = (resistance[0] if resistance else close * 1.10) if action == "BUY" else None

        return {
            "method": "fallback_deterministic",
            "symbol": symbol,
            "action": action,
            "confidence": round(confidence, 3),
            "current_close": close,
            "trend_20d": trend,
            "rsi_14d": rsi,
            "volatility_20d": volatility,
            "volume_ratio": vol_ratio,
            "patterns": patterns,
            "news_sentiment": avg_sent,
            "negative_events": n_neg,
            "bull_signals": bull_signals,
            "bear_signals": bear_signals,
            "support_levels": support,
            "resistance_levels": resistance,
            "stop_loss": round(stop_loss, 2) if stop_loss else None,
            "take_profit": round(take_profit, 2) if take_profit else None,
            "user_holds": bool(held),
            "position_pnl_pct": (position or {}).get("pnl_pct") if held else None,
            "summary": (
                f"{action}（信心 {int(confidence*100)}%）— "
                f"{bull} 个利多信号 vs {bear} 个利空信号"
            ),
        }

    @staticmethod
    def _extract_symbol(text: str) -> str:
        """Extract a stock symbol like 600519.SH from arbitrary text."""
        import re
        m = re.search(r"\b\d{6}\.(SH|SZ|BJ)\b", text or "")
        return m.group(0) if m else ""


def _get(observations: list, name: str):
    for o in observations:
        if o.name == name and o.error is None:
            return o.output
    return None
