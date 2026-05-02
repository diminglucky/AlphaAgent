"""Analysis orchestrator: wires all agents and produces the final report."""

from __future__ import annotations

from typing import Any, Optional

from libs.llm_analyst.agents import (
    FundamentalAnalyst,
    MarketAnalyst,
    NewsAnalyst,
    PortfolioManager,
    RiskOfficer,
    TechnicalAnalyst,
)
from libs.llm_analyst.decision import AnalysisReport, DecisionAggregator
from libs.llm_analyst.llm_client import LLMClient, LLMConfig


class AnalysisOrchestrator:
    """
    Coordinates the four analyst agents and produces an AnalysisReport.

    Usage::

        orchestrator = AnalysisOrchestrator()
        report = orchestrator.analyze(
            symbol="600519.SH",
            features={...},          # TechnicalFeatures as dict
            signal_score=0.42,
            signal_conf=0.68,
            instrument={...},        # Instrument metadata dict
            news_items=[...],        # list[dict] from NewsRepository
            risk_flags=[...],        # list[str] active risk flags
            portfolio_context="当前仓位 5%，上限 30%",
        )
    """

    def __init__(self, llm_config: Optional[LLMConfig] = None) -> None:
        client = LLMClient(llm_config)
        self._market = MarketAnalyst(client)
        self._tech = TechnicalAnalyst(client)
        self._news = NewsAnalyst(client)
        self._fund = FundamentalAnalyst(client)
        self._pm = PortfolioManager(client)
        self._risk = RiskOfficer(client)
        self._agg = DecisionAggregator()
        self._llm_powered = client.is_llm_available()

    def analyze(
        self,
        symbol: str,
        features: dict[str, Any],
        signal_score: float,
        signal_conf: float,
        instrument: dict[str, Any],
        news_items: list[dict[str, Any]],
        risk_flags: list[str],
        portfolio_context: str = "无特殊持仓约束",
        market_bars: Optional[list[float]] = None,
        portfolio_positions: Optional[list[dict]] = None,
        portfolio_total_value: float = 0.0,
        portfolio_cash: float = 0.0,
        proposed_action: str = "BUY",
    ) -> AnalysisReport:
        """Run all 6 agents in sequence and return the aggregated report.

        New optional inputs:
        - market_bars: index/proxy close prices for regime detection
        - portfolio_positions: holdings list for the PortfolioManager
        - portfolio_total_value, portfolio_cash, proposed_action
        """

        # Layer 1: market regime
        market_report = self._market.analyze(symbol, market_bars or [])

        # Layer 2-3: stock-level analysis
        tech_report = self._tech.analyze(symbol, features, signal_score, signal_conf)
        news_report = self._news.analyze(symbol, news_items)
        fund_report = self._fund.analyze(symbol, instrument, signal_score, risk_flags)

        # Layer 4: portfolio context
        pm_report = self._pm.analyze(
            symbol,
            portfolio_positions or [],
            portfolio_total_value,
            portfolio_cash,
            proposed_action=proposed_action,
        )

        reports = {
            "MarketAnalyst": market_report,
            "TechnicalAnalyst": tech_report,
            "NewsAnalyst": news_report,
            "FundamentalAnalyst": fund_report,
            "PortfolioManager": pm_report,
        }

        risk_report = self._risk.review(symbol, reports, risk_flags, portfolio_context)
        reports["RiskOfficer"] = risk_report

        return self._agg.aggregate(symbol, reports, llm_powered=self._llm_powered)
