"""Multi-agent analyst roles for stock analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from libs.llm_analyst.llm_client import LLMClient


class AnalystView(str, Enum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"


@dataclass(frozen=True)
class AgentReport:
    """Structured output from one analyst agent."""
    agent: str
    view: AnalystView
    confidence: float          # 0.0–1.0
    reasoning: str
    key_points: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    data_used: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Technical Analyst
# ---------------------------------------------------------------------------

_TECH_SYSTEM = """你是一名专业的A股技术面分析师。
根据用户提供的技术指标数据，分析股票的技术面信号。
请从以下几个维度分析：趋势（均线排列、价格位置）、动量（RSI、近期涨跌幅）、成交量（量价配合）、波动性。
输出格式必须是JSON：
{
  "view": "BULLISH"|"NEUTRAL"|"BEARISH",
  "confidence": 0.0~1.0,
  "reasoning": "综合分析理由（中文，2-3句）",
  "key_points": ["要点1", "要点2", "要点3"],
  "risk_flags": ["风险点（如有）"]
}"""

_TECH_USER_TMPL = """股票：{symbol}
技术指标数据：
- 最新收盘价：{close}
- 5日均线：{ma5}
- 20日均线：{ma20}
- 60日均线：{ma60}
- RSI(14)：{rsi14}
- 1日涨跌幅：{ret1d:.2%}
- 5日涨跌幅：{ret5d:.2%}
- 20日波动率：{vol20d:.4f}
- 5日量比：{vol_ratio:.2f}
- 换手率：{turnover:.2f}%
- 技术面总分（-1~1）：{signal_score:.3f}
- 置信度：{signal_conf:.2%}"""


class TechnicalAnalyst:
    """Analyzes price/volume technical signals."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def analyze(self, symbol: str, features: dict[str, Any], signal_score: float, signal_conf: float) -> AgentReport:
        if self._client.is_llm_available():
            return self._llm_analyze(symbol, features, signal_score, signal_conf)
        return self._rule_analyze(symbol, features, signal_score, signal_conf)

    def _llm_analyze(self, symbol: str, features: dict[str, Any], signal_score: float, signal_conf: float) -> AgentReport:
        prompt = _TECH_USER_TMPL.format(
            symbol=symbol,
            close=features.get("close", "N/A"),
            ma5=features.get("ma_5d", "N/A"),
            ma20=features.get("ma_20d", "N/A"),
            ma60=features.get("ma_60d", "N/A"),
            rsi14=features.get("rsi_14d", "N/A"),
            ret1d=features.get("returns_1d", 0.0),
            ret5d=features.get("returns_5d", 0.0),
            vol20d=features.get("volatility_20d", 0.0),
            vol_ratio=features.get("volume_ratio_5d", 1.0),
            turnover=features.get("turnover_rate", 0.0),
            signal_score=signal_score,
            signal_conf=signal_conf,
        )
        result = self._client.chat_json(_TECH_SYSTEM, prompt)
        return self._parse_json(result, symbol, features)

    def _rule_analyze(self, symbol: str, features: dict[str, Any], signal_score: float, signal_conf: float) -> AgentReport:
        if signal_score > 0.3:
            view, reasoning = AnalystView.BULLISH, f"技术面综合得分 {signal_score:.2f}，量价配合良好，趋势偏多"
        elif signal_score < -0.3:
            view, reasoning = AnalystView.BEARISH, f"技术面综合得分 {signal_score:.2f}，趋势偏空，需谨慎"
        else:
            view, reasoning = AnalystView.NEUTRAL, f"技术面综合得分 {signal_score:.2f}，信号中性，等待方向"

        risk_flags = []
        if features.get("volatility_20d", 0) > 0.03:
            risk_flags.append("HIGH_VOLATILITY")
        if features.get("rsi_14d", 50) and features.get("rsi_14d", 50) > 75:
            risk_flags.append("OVERBOUGHT")

        return AgentReport(
            agent="TechnicalAnalyst",
            view=view,
            confidence=signal_conf,
            reasoning=reasoning,
            key_points=[f"信号分: {signal_score:.2f}", f"置信度: {signal_conf:.0%}"],
            risk_flags=risk_flags,
            data_used={"signal_score": signal_score, "signal_conf": signal_conf},
        )

    def _parse_json(self, data: dict, symbol: str, features: dict) -> AgentReport:
        try:
            view = AnalystView(data.get("view", "NEUTRAL"))
        except ValueError:
            view = AnalystView.NEUTRAL
        return AgentReport(
            agent="TechnicalAnalyst",
            view=view,
            confidence=float(data.get("confidence", 0.5)),
            reasoning=str(data.get("reasoning", "")),
            key_points=list(data.get("key_points", [])),
            risk_flags=list(data.get("risk_flags", [])),
            data_used={"symbol": symbol},
        )


# ---------------------------------------------------------------------------
# News Analyst
# ---------------------------------------------------------------------------

_NEWS_SYSTEM = """你是一名专业的A股新闻与事件分析师。
根据用户提供的最新新闻摘要，分析这些新闻对股票的影响。
重点关注：利好/利空方向、事件重要性、对股价的可能影响。
输出格式必须是JSON：
{
  "view": "BULLISH"|"NEUTRAL"|"BEARISH",
  "confidence": 0.0~1.0,
  "reasoning": "综合分析理由（中文，2-3句）",
  "key_points": ["关键新闻点1", "关键新闻点2"],
  "risk_flags": ["风险点（如有）"]
}"""

_NEWS_USER_TMPL = """股票：{symbol}
近期相关新闻摘要（共{count}条）：
{news_text}
平均情绪评分：{avg_sentiment:.2f}（-1极负面，+1极正面）
最高紧迫度：{max_urgency:.2f}"""


class NewsAnalyst:
    """Analyzes news sentiment and events."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def analyze(self, symbol: str, news_items: list[dict[str, Any]]) -> AgentReport:
        if not news_items:
            return AgentReport(
                agent="NewsAnalyst",
                view=AnalystView.NEUTRAL,
                confidence=0.3,
                reasoning="无近期相关新闻",
                key_points=["无近期新闻，无法判断新闻面"],
            )
        if self._client.is_llm_available():
            return self._llm_analyze(symbol, news_items)
        return self._rule_analyze(symbol, news_items)

    def _llm_analyze(self, symbol: str, news_items: list[dict[str, Any]]) -> AgentReport:
        news_text = "\n".join(
            f"- [{i.get('event_type','NEWS')}] {i.get('summary', i.get('title', ''))}"
            f"（情绪: {i.get('sentiment_score', 0):.2f}）"
            for i in news_items[:8]
        )
        avg_sentiment = sum(i.get("sentiment_score", 0) for i in news_items) / len(news_items)
        max_urgency = max((i.get("urgency_score", 0) for i in news_items), default=0)

        prompt = _NEWS_USER_TMPL.format(
            symbol=symbol,
            count=len(news_items),
            news_text=news_text,
            avg_sentiment=avg_sentiment,
            max_urgency=max_urgency,
        )
        result = self._client.chat_json(_NEWS_SYSTEM, prompt)
        return self._parse_json(result, symbol)

    def _rule_analyze(self, symbol: str, news_items: list[dict[str, Any]]) -> AgentReport:
        if not news_items:
            return AgentReport(agent="NewsAnalyst", view=AnalystView.NEUTRAL, confidence=0.3, reasoning="无新闻数据")

        avg_sentiment = sum(i.get("sentiment_score", 0) for i in news_items) / len(news_items)
        if avg_sentiment > 0.3:
            view = AnalystView.BULLISH
            reasoning = f"近{len(news_items)}条新闻平均情绪得分 {avg_sentiment:.2f}，新闻面偏正面"
        elif avg_sentiment < -0.3:
            view = AnalystView.BEARISH
            reasoning = f"近{len(news_items)}条新闻平均情绪得分 {avg_sentiment:.2f}，新闻面偏负面"
        else:
            view = AnalystView.NEUTRAL
            reasoning = f"近{len(news_items)}条新闻平均情绪得分 {avg_sentiment:.2f}，新闻面中性"

        return AgentReport(
            agent="NewsAnalyst",
            view=view,
            confidence=min(0.8, 0.3 + len(news_items) * 0.05),
            reasoning=reasoning,
            key_points=[f"共{len(news_items)}条相关新闻", f"平均情绪: {avg_sentiment:.2f}"],
            data_used={"news_count": len(news_items), "avg_sentiment": avg_sentiment},
        )

    def _parse_json(self, data: dict, symbol: str) -> AgentReport:
        try:
            view = AnalystView(data.get("view", "NEUTRAL"))
        except ValueError:
            view = AnalystView.NEUTRAL
        return AgentReport(
            agent="NewsAnalyst",
            view=view,
            confidence=float(data.get("confidence", 0.5)),
            reasoning=str(data.get("reasoning", "")),
            key_points=list(data.get("key_points", [])),
            risk_flags=list(data.get("risk_flags", [])),
            data_used={"symbol": symbol},
        )


# ---------------------------------------------------------------------------
# Fundamental Analyst (lightweight, uses basic valuation proxies)
# ---------------------------------------------------------------------------

_FUND_SYSTEM = """你是一名专业的A股基本面分析师。
根据用户提供的基本面数据（估值、行业、状态），给出基本面评级。
输出格式必须是JSON：
{
  "view": "BULLISH"|"NEUTRAL"|"BEARISH",
  "confidence": 0.0~1.0,
  "reasoning": "综合分析理由（中文，2-3句）",
  "key_points": ["基本面要点1", "基本面要点2"],
  "risk_flags": ["风险点（如有）"]
}"""

_FUND_USER_TMPL = """股票：{symbol}
基本面数据：
- 行业：{industry}
- 上市状态：{status}
- 是否ST：{is_st}
- 涨跌停状态（近期风控标记）：{risk_flags}
- 技术面信号分（参考）：{signal_score:.3f}"""


class FundamentalAnalyst:
    """Analyzes fundamental data (simplified without full financial DB)."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def analyze(self, symbol: str, instrument: dict[str, Any], signal_score: float, risk_flags: list[str]) -> AgentReport:
        if self._client.is_llm_available():
            return self._llm_analyze(symbol, instrument, signal_score, risk_flags)
        return self._rule_analyze(symbol, instrument, signal_score, risk_flags)

    def _llm_analyze(self, symbol: str, instrument: dict, signal_score: float, risk_flags: list[str]) -> AgentReport:
        prompt = _FUND_USER_TMPL.format(
            symbol=symbol,
            industry=instrument.get("industry", "未知"),
            status=instrument.get("status", "正常"),
            is_st=instrument.get("is_st", False),
            risk_flags=", ".join(risk_flags) if risk_flags else "无",
            signal_score=signal_score,
        )
        result = self._client.chat_json(_FUND_SYSTEM, prompt)
        return self._parse_json(result, symbol)

    def _rule_analyze(self, symbol: str, instrument: dict, signal_score: float, risk_flags: list[str]) -> AgentReport:
        flags = set(risk_flags)
        is_st = instrument.get("is_st", False)
        status = instrument.get("status", "正常")

        if is_st or "ST_STOCK" in flags:
            return AgentReport(
                agent="FundamentalAnalyst",
                view=AnalystView.BEARISH,
                confidence=0.85,
                reasoning="ST 股票，存在退市风险，基本面看空",
                risk_flags=["ST_STOCK"],
            )
        if status not in ("正常", "active", "ACTIVE", "listed", "LISTED", ""):
            return AgentReport(
                agent="FundamentalAnalyst",
                view=AnalystView.BEARISH,
                confidence=0.7,
                reasoning=f"股票状态异常（{status}），谨慎对待",
                risk_flags=["ABNORMAL_STATUS"],
            )
        if "HALT" in flags:
            return AgentReport(
                agent="FundamentalAnalyst",
                view=AnalystView.NEUTRAL,
                confidence=0.6,
                reasoning="股票存在停牌风险标记，建议观望",
                risk_flags=["HALT"],
            )

        view = AnalystView.BULLISH if signal_score > 0.2 else (AnalystView.BEARISH if signal_score < -0.2 else AnalystView.NEUTRAL)
        return AgentReport(
            agent="FundamentalAnalyst",
            view=view,
            confidence=0.45,
            reasoning=f"无重大基本面异常，行业：{instrument.get('industry', '未知')}，随技术面方向",
            key_points=[f"行业: {instrument.get('industry', '未知')}", "无重大基本面风险"],
        )

    def _parse_json(self, data: dict, symbol: str) -> AgentReport:
        try:
            view = AnalystView(data.get("view", "NEUTRAL"))
        except ValueError:
            view = AnalystView.NEUTRAL
        return AgentReport(
            agent="FundamentalAnalyst",
            view=view,
            confidence=float(data.get("confidence", 0.5)),
            reasoning=str(data.get("reasoning", "")),
            key_points=list(data.get("key_points", [])),
            risk_flags=list(data.get("risk_flags", [])),
        )


# ---------------------------------------------------------------------------
# Risk Officer
# ---------------------------------------------------------------------------

_RISK_SYSTEM = """你是一名专业的A股风险官（Risk Officer）。
你的职责是审查其他分析师的意见，结合风险数据，做出最终风控裁决。
输出格式必须是JSON：
{
  "view": "BULLISH"|"NEUTRAL"|"BEARISH",
  "confidence": 0.0~1.0,
  "reasoning": "综合风控说明（中文，2-3句）",
  "key_points": ["风控要点"],
  "risk_flags": ["风险标记列表"],
  "approved": true|false
}"""

_RISK_USER_TMPL = """股票：{symbol}
技术面观点：{tech_view}（置信度：{tech_conf:.0%}）
基本面观点：{fund_view}（置信度：{fund_conf:.0%}）
新闻面观点：{news_view}（置信度：{news_conf:.0%}）

已识别的风险标记：{risk_flags}
组合暴露说明：{portfolio_context}
请给出风控裁决，并决定是否批准该方向。"""


class RiskOfficer:
    """Reviews all analyst views and applies risk filters."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def review(
        self,
        symbol: str,
        reports: dict[str, AgentReport],
        risk_flags: list[str],
        portfolio_context: str = "无特殊持仓约束",
    ) -> AgentReport:
        if self._client.is_llm_available():
            return self._llm_review(symbol, reports, risk_flags, portfolio_context)
        return self._rule_review(symbol, reports, risk_flags)

    def _llm_review(self, symbol: str, reports: dict[str, AgentReport], risk_flags: list[str], portfolio_context: str) -> AgentReport:
        tech = reports.get("TechnicalAnalyst")
        fund = reports.get("FundamentalAnalyst")
        news = reports.get("NewsAnalyst")

        prompt = _RISK_USER_TMPL.format(
            symbol=symbol,
            tech_view=tech.view.value if tech else "N/A",
            tech_conf=tech.confidence if tech else 0,
            fund_view=fund.view.value if fund else "N/A",
            fund_conf=fund.confidence if fund else 0,
            news_view=news.view.value if news else "N/A",
            news_conf=news.confidence if news else 0,
            risk_flags=", ".join(risk_flags) if risk_flags else "无",
            portfolio_context=portfolio_context,
        )
        result = self._client.chat_json(_RISK_SYSTEM, prompt)
        return self._parse_json(result, symbol, risk_flags)

    def _rule_review(self, symbol: str, reports: dict[str, AgentReport], risk_flags: list[str]) -> AgentReport:
        blocking_flags = {"ST_STOCK", "HALT", "LIMIT_DOWN", "ABNORMAL_STATUS"}
        blocks = set(risk_flags) & blocking_flags

        if blocks:
            return AgentReport(
                agent="RiskOfficer",
                view=AnalystView.BEARISH,
                confidence=0.9,
                reasoning=f"风控标记触发拦截：{', '.join(blocks)}，不建议操作",
                risk_flags=list(blocks),
                data_used={"approved": False, "block_reason": list(blocks)},
            )

        bullish = sum(1 for r in reports.values() if r.view == AnalystView.BULLISH)
        bearish = sum(1 for r in reports.values() if r.view == AnalystView.BEARISH)

        if bullish > bearish:
            view = AnalystView.BULLISH
            reasoning = f"{bullish}/{len(reports)} 个分析师看多，综合风控通过"
            approved = True
        elif bearish > bullish:
            view = AnalystView.BEARISH
            reasoning = f"{bearish}/{len(reports)} 个分析师看空，建议谨慎"
            approved = True
        else:
            view = AnalystView.NEUTRAL
            reasoning = "多空意见分歧，建议观望"
            approved = True

        all_flags = list({f for r in reports.values() for f in r.risk_flags} | set(risk_flags))
        return AgentReport(
            agent="RiskOfficer",
            view=view,
            confidence=0.65,
            reasoning=reasoning,
            risk_flags=all_flags,
            data_used={"approved": approved, "bullish_count": bullish, "bearish_count": bearish},
        )

    def _parse_json(self, data: dict, symbol: str, risk_flags: list[str]) -> AgentReport:
        try:
            view = AnalystView(data.get("view", "NEUTRAL"))
        except ValueError:
            view = AnalystView.NEUTRAL
        return AgentReport(
            agent="RiskOfficer",
            view=view,
            confidence=float(data.get("confidence", 0.5)),
            reasoning=str(data.get("reasoning", "")),
            key_points=list(data.get("key_points", [])),
            risk_flags=list(data.get("risk_flags", risk_flags)),
            data_used={"approved": bool(data.get("approved", True))},
        )


# ---------------------------------------------------------------------------
# Market regime analyst (§6.4 第 1 角色)
# ---------------------------------------------------------------------------

class MarketAnalyst:
    """Detects overall market regime: risk-on / risk-off / range-bound.

    Uses a recent index price history (proxied by averaging the symbol's own
    bars when no index series is provided) to classify regime. Output is used
    by DecisionAggregator to apply a `regime_adjustment` per §6.2.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def analyze(self, symbol: str, market_bars: list[float]) -> AgentReport:
        if len(market_bars) < 5:
            return AgentReport(
                agent="MarketAnalyst",
                view=AnalystView.NEUTRAL,
                confidence=0.3,
                reasoning="历史数据不足，无法判断大盘 regime",
            )

        # Simple regime: trend slope + volatility
        first, last = market_bars[0], market_bars[-1]
        cumret = (last - first) / first if first else 0.0
        vols = []
        for i in range(1, len(market_bars)):
            if market_bars[i - 1]:
                vols.append((market_bars[i] - market_bars[i - 1]) / market_bars[i - 1])
        vol = (sum(v * v for v in vols) / len(vols)) ** 0.5 if vols else 0.0

        if cumret > 0.04 and vol < 0.025:
            regime = "risk_on"
            view = AnalystView.BULLISH
            adj = 0.15
            reasoning = (
                f"近期累计涨幅 {cumret:+.1%}，波动率 {vol:.1%} 偏低 → 风险偏好扩张"
            )
        elif cumret < -0.04:
            regime = "risk_off"
            view = AnalystView.BEARISH
            adj = -0.15
            reasoning = f"近期累计跌幅 {cumret:+.1%} → 风险收缩，应降低暴露"
        elif vol > 0.04:
            regime = "high_vol_range"
            view = AnalystView.NEUTRAL
            adj = -0.05
            reasoning = f"波动率 {vol:.1%} 偏高，建议观望"
        else:
            regime = "range_bound"
            view = AnalystView.NEUTRAL
            adj = 0.0
            reasoning = f"震荡市，累计涨幅 {cumret:+.1%}、波动率 {vol:.1%}"

        return AgentReport(
            agent="MarketAnalyst",
            view=view,
            confidence=0.6,
            reasoning=reasoning,
            key_points=[regime],
            data_used={
                "regime": regime,
                "cum_return": round(cumret, 4),
                "volatility": round(vol, 4),
                "regime_adjustment": adj,
            },
        )


# ---------------------------------------------------------------------------
# Portfolio Manager (§6.4 第 5 角色)
# ---------------------------------------------------------------------------

class PortfolioManager:
    """Considers existing positions, cash, and concentration before voting.

    Outputs a view that incorporates `exposure_penalty` per §6.2.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def analyze(
        self,
        symbol: str,
        positions: list[dict],
        portfolio_total_value: float,
        cash: float,
        proposed_action: str = "BUY",
    ) -> AgentReport:
        cur_pos = next((p for p in positions if p.get("symbol") == symbol), None)
        cur_value = cur_pos.get("market_value", 0.0) if cur_pos else 0.0
        cur_qty = cur_pos.get("quantity", 0) if cur_pos else 0
        weight = (cur_value / portfolio_total_value) if portfolio_total_value > 0 else 0.0
        cash_ratio = (cash / portfolio_total_value) if portfolio_total_value > 0 else 0.0
        n_holdings = len(positions)

        flags: list[str] = []
        if weight > 0.30:
            flags.append("OVERWEIGHT_POSITION")
        if n_holdings > 0 and cash_ratio < 0.05:
            flags.append("LOW_CASH")
        if n_holdings > 15:
            flags.append("OVER_DIVERSIFIED")

        # Action-specific posture
        if proposed_action == "BUY":
            if "OVERWEIGHT_POSITION" in flags:
                view = AnalystView.BEARISH
                reasoning = (
                    f"当前持仓权重已达 {weight:.0%}（>30%），不建议加仓"
                )
                conf = 0.85
            elif "LOW_CASH" in flags:
                view = AnalystView.BEARISH
                reasoning = f"现金占比仅 {cash_ratio:.0%}，加仓后流动性紧张"
                conf = 0.7
            elif weight == 0:
                view = AnalystView.BULLISH
                reasoning = f"未持仓 {symbol}，组合仍有 {cash_ratio:.0%} 现金可建仓"
                conf = 0.6
            else:
                view = AnalystView.NEUTRAL
                reasoning = f"已持有 {symbol} 权重 {weight:.0%}，组合中性"
                conf = 0.5
        elif proposed_action == "SELL":
            if cur_qty == 0:
                view = AnalystView.NEUTRAL
                reasoning = "未持仓，无需考虑卖出"
                conf = 0.4
            elif weight > 0.30:
                view = AnalystView.BULLISH  # bullish on the SELL action
                reasoning = f"重仓 {weight:.0%}，建议减仓再平衡"
                conf = 0.8
            else:
                view = AnalystView.NEUTRAL
                reasoning = f"持仓 {weight:.0%} 在合理区间，不必急于卖出"
                conf = 0.5
        else:
            view = AnalystView.NEUTRAL
            reasoning = "持仓侧无特别建议"
            conf = 0.4

        # Exposure penalty per §6.2
        exposure_penalty = max(0.0, weight - 0.20) * 0.5

        return AgentReport(
            agent="PortfolioManager",
            view=view,
            confidence=conf,
            reasoning=reasoning,
            risk_flags=flags,
            key_points=[
                f"当前权重 {weight:.0%}",
                f"现金占比 {cash_ratio:.0%}",
                f"持仓数 {n_holdings}",
            ],
            data_used={
                "current_weight": round(weight, 4),
                "cash_ratio": round(cash_ratio, 4),
                "n_holdings": n_holdings,
                "exposure_penalty": round(exposure_penalty, 4),
                "proposed_action": proposed_action,
            },
        )
