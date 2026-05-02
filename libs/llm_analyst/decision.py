"""Decision aggregator: combines all agent reports into a final AnalysisReport."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from libs.llm_analyst.agents import AgentReport, AnalystView
from libs.quant_core.enums import RecommendationAction


# ---------------------------------------------------------------------------
# Final report structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnalysisReport:
    """
    Aggregated analysis report produced by the multi-agent system.

    Fields mirror the existing Recommendation domain model so they can be
    directly used by recommendation endpoints.
    """
    symbol: str
    action: RecommendationAction       # BUY / HOLD / SELL
    confidence: float                  # 0.0–1.0
    summary: str                       # One-line human-readable summary
    reasoning: str                     # Detailed multi-paragraph reasoning
    risk_flags: list[str]
    components: dict[str, Any]         # Per-agent breakdown
    approved: bool                     # RiskOfficer approval
    generated_at: datetime = field(default_factory=datetime.now)
    llm_powered: bool = False          # True when LLM was used


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

class DecisionAggregator:
    """
    Combines outputs from TechnicalAnalyst, FundamentalAnalyst,
    NewsAnalyst, and RiskOfficer into a single AnalysisReport.

    Weighting scheme (adjustable):
        Technical:   40 %
        News:        30 %
        Fundamental: 30 %

    RiskOfficer has veto power: if it returns BEARISH with confidence > 0.8
    and approved=False, the final action is overridden to HOLD/SELL.
    """

    WEIGHTS: dict[str, float] = {
        "MarketAnalyst": 0.10,
        "TechnicalAnalyst": 0.30,
        "NewsAnalyst": 0.20,
        "FundamentalAnalyst": 0.20,
        "PortfolioManager": 0.20,
    }

    # -1 = full bearish weight, +1 = full bullish weight
    VIEW_SCORE: dict[AnalystView, float] = {
        AnalystView.BULLISH: 1.0,
        AnalystView.NEUTRAL: 0.0,
        AnalystView.BEARISH: -1.0,
    }

    def aggregate(
        self,
        symbol: str,
        reports: dict[str, AgentReport],
        llm_powered: bool = False,
    ) -> AnalysisReport:
        risk_report = reports.get("RiskOfficer")
        analyst_reports = {k: v for k, v in reports.items() if k != "RiskOfficer"}

        # Weighted vote
        weighted_score = 0.0
        weight_sum = 0.0
        for agent_name, weight in self.WEIGHTS.items():
            report = analyst_reports.get(agent_name)
            if report is None:
                continue
            score = self.VIEW_SCORE[report.view] * report.confidence
            weighted_score += score * weight
            weight_sum += weight

        if weight_sum > 0:
            weighted_score /= weight_sum

        # Map score to action
        if weighted_score > 0.25:
            raw_action = RecommendationAction.BUY
        elif weighted_score < -0.25:
            raw_action = RecommendationAction.SELL
        else:
            raw_action = RecommendationAction.HOLD

        # Risk officer veto
        approved = True
        if risk_report:
            approved = bool(risk_report.data_used.get("approved", True))
            if not approved or (
                risk_report.view == AnalystView.BEARISH
                and risk_report.confidence >= 0.8
                and raw_action == RecommendationAction.BUY
            ):
                raw_action = RecommendationAction.HOLD
                approved = False

        # Overall confidence
        all_confs = [r.confidence for r in reports.values()]
        confidence = round(sum(all_confs) / len(all_confs) if all_confs else 0.5, 3)

        # Collect all risk flags
        risk_flags: list[str] = list({
            f
            for r in reports.values()
            for f in r.risk_flags
        })

        # Build summary and reasoning
        action_str = {"BUY": "建议买入", "SELL": "建议卖出", "HOLD": "建议观望"}[raw_action.value]
        tech_view = analyst_reports.get("TechnicalAnalyst")
        news_view = analyst_reports.get("NewsAnalyst")
        summary = (
            f"{symbol} — {action_str}（综合置信度 {confidence:.0%}）"
        )

        reasoning_parts = [f"**综合结论**：{summary}"]
        for key in (
            "MarketAnalyst",
            "TechnicalAnalyst",
            "NewsAnalyst",
            "FundamentalAnalyst",
            "PortfolioManager",
            "RiskOfficer",
        ):
            r = reports.get(key)
            if r:
                label_map = {
                    "MarketAnalyst": "市场层",
                    "TechnicalAnalyst": "技术面",
                    "NewsAnalyst": "新闻面",
                    "FundamentalAnalyst": "基本面",
                    "PortfolioManager": "组合管理",
                    "RiskOfficer": "风控官",
                }
                view_cn = {"BULLISH": "看多", "NEUTRAL": "中性", "BEARISH": "看空"}[r.view.value]
                reasoning_parts.append(
                    f"\n**{label_map[key]}**（{view_cn} {r.confidence:.0%}）：{r.reasoning}"
                )
                if r.key_points:
                    reasoning_parts.append("• " + "\n• ".join(r.key_points))

        # Components payload
        components: dict[str, Any] = {
            agent: {
                "view": r.view.value,
                "confidence": r.confidence,
                "reasoning": r.reasoning,
                "key_points": r.key_points,
                "risk_flags": r.risk_flags,
            }
            for agent, r in reports.items()
        }
        components["weighted_score"] = round(weighted_score, 4)

        return AnalysisReport(
            symbol=symbol,
            action=raw_action,
            confidence=confidence,
            summary=summary,
            reasoning="\n".join(reasoning_parts),
            risk_flags=risk_flags,
            components=components,
            approved=approved,
            llm_powered=llm_powered,
        )
