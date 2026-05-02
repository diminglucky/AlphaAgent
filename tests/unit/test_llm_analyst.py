"""Unit tests for the multi-agent LLM analyst system."""

from datetime import date

import pytest

from libs.llm_analyst.agents import (
    AnalystView,
    FundamentalAnalyst,
    NewsAnalyst,
    RiskOfficer,
    TechnicalAnalyst,
)
from libs.llm_analyst.decision import DecisionAggregator
from libs.llm_analyst.llm_client import LLMClient, LLMConfig, LLMProvider
from libs.llm_analyst.orchestrator import AnalysisOrchestrator
from libs.quant_core.enums import RecommendationAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _keyword_client() -> LLMClient:
    cfg = LLMConfig()
    cfg.provider = LLMProvider.KEYWORD
    return LLMClient(cfg)


def _make_features(signal_score: float = 0.5) -> dict:
    return {
        "symbol": "600519.SH",
        "as_of_date": date.today(),
        "close": 1720.0,
        "returns_1d": 0.01,
        "returns_5d": 0.03,
        "returns_20d": 0.05,
        "volatility_20d": 0.015,
        "volume": 5000,
        "volume_ratio_5d": 1.2,
        "turnover_rate": 2.5,
        "rsi_14d": 55.0,
        "ma_5d": 1700.0,
        "ma_20d": 1680.0,
        "ma_60d": 1650.0,
    }


def _good_instrument() -> dict:
    return {"symbol": "600519.SH", "industry": "白酒", "status": "listed", "is_st": False}


def _st_instrument() -> dict:
    return {"symbol": "600519.SH", "industry": "白酒", "status": "listed", "is_st": True}


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

def test_keyword_client_not_available() -> None:
    client = _keyword_client()
    assert client.is_llm_available() is False


def test_keyword_client_chat_returns_empty() -> None:
    client = _keyword_client()
    assert client.chat("sys", "user") == ""


def test_keyword_client_chat_json_returns_empty_dict() -> None:
    client = _keyword_client()
    assert client.chat_json("sys", "user") == {}


# ---------------------------------------------------------------------------
# TechnicalAnalyst (rule-based)
# ---------------------------------------------------------------------------

def test_technical_analyst_bullish() -> None:
    analyst = TechnicalAnalyst(_keyword_client())
    report = analyst.analyze("600519.SH", _make_features(), signal_score=0.55, signal_conf=0.7)
    assert report.agent == "TechnicalAnalyst"
    assert report.view == AnalystView.BULLISH
    assert 0.0 <= report.confidence <= 1.0


def test_technical_analyst_bearish() -> None:
    analyst = TechnicalAnalyst(_keyword_client())
    report = analyst.analyze("600519.SH", _make_features(), signal_score=-0.45, signal_conf=0.65)
    assert report.view == AnalystView.BEARISH


def test_technical_analyst_neutral() -> None:
    analyst = TechnicalAnalyst(_keyword_client())
    report = analyst.analyze("600519.SH", _make_features(), signal_score=0.1, signal_conf=0.3)
    assert report.view == AnalystView.NEUTRAL


def test_technical_analyst_high_volatility_flag() -> None:
    analyst = TechnicalAnalyst(_keyword_client())
    feats = _make_features()
    feats["volatility_20d"] = 0.05
    report = analyst.analyze("600519.SH", feats, signal_score=0.4, signal_conf=0.6)
    assert "HIGH_VOLATILITY" in report.risk_flags


# ---------------------------------------------------------------------------
# NewsAnalyst (rule-based)
# ---------------------------------------------------------------------------

def test_news_analyst_no_news() -> None:
    analyst = NewsAnalyst(_keyword_client())
    report = analyst.analyze("600519.SH", [])
    assert report.agent == "NewsAnalyst"
    assert report.view == AnalystView.NEUTRAL
    assert report.confidence < 0.5


def test_news_analyst_positive_news() -> None:
    analyst = NewsAnalyst(_keyword_client())
    news = [{"sentiment_score": 0.8, "summary": "超预期业绩", "event_type": "EARNINGS"}] * 3
    report = analyst.analyze("600519.SH", news)
    assert report.view == AnalystView.BULLISH


def test_news_analyst_negative_news() -> None:
    analyst = NewsAnalyst(_keyword_client())
    news = [{"sentiment_score": -0.7, "summary": "监管处罚", "event_type": "REGULATORY"}] * 3
    report = analyst.analyze("600519.SH", news)
    assert report.view == AnalystView.BEARISH


# ---------------------------------------------------------------------------
# FundamentalAnalyst (rule-based)
# ---------------------------------------------------------------------------

def test_fundamental_analyst_st_stock_is_bearish() -> None:
    analyst = FundamentalAnalyst(_keyword_client())
    report = analyst.analyze("600519.SH", _st_instrument(), signal_score=0.5, risk_flags=[])
    assert report.view == AnalystView.BEARISH
    assert "ST_STOCK" in report.risk_flags


def test_fundamental_analyst_normal_stock() -> None:
    analyst = FundamentalAnalyst(_keyword_client())
    report = analyst.analyze("600519.SH", _good_instrument(), signal_score=0.3, risk_flags=[])
    assert report.agent == "FundamentalAnalyst"
    assert report.view in {AnalystView.BULLISH, AnalystView.NEUTRAL, AnalystView.BEARISH}


def test_fundamental_analyst_halt_flag() -> None:
    analyst = FundamentalAnalyst(_keyword_client())
    report = analyst.analyze("600519.SH", _good_instrument(), signal_score=0.1, risk_flags=["HALT"])
    assert "HALT" in report.risk_flags


# ---------------------------------------------------------------------------
# RiskOfficer (rule-based)
# ---------------------------------------------------------------------------

def test_risk_officer_blocks_st() -> None:
    officer = RiskOfficer(_keyword_client())
    reports = {
        "TechnicalAnalyst": TechnicalAnalyst(_keyword_client()).analyze("S", _make_features(), 0.5, 0.7),
    }
    report = officer.review("S", reports, risk_flags=["ST_STOCK"])
    assert report.view == AnalystView.BEARISH
    assert report.data_used.get("approved") is False


def test_risk_officer_approves_bullish_consensus() -> None:
    officer = RiskOfficer(_keyword_client())
    from libs.llm_analyst.agents import AgentReport
    reports = {
        "TechnicalAnalyst": AgentReport("TechnicalAnalyst", AnalystView.BULLISH, 0.7, "ok"),
        "NewsAnalyst": AgentReport("NewsAnalyst", AnalystView.BULLISH, 0.65, "ok"),
        "FundamentalAnalyst": AgentReport("FundamentalAnalyst", AnalystView.NEUTRAL, 0.5, "ok"),
    }
    report = officer.review("600519.SH", reports, risk_flags=[])
    assert report.view == AnalystView.BULLISH
    assert report.data_used.get("approved") is True


# ---------------------------------------------------------------------------
# DecisionAggregator
# ---------------------------------------------------------------------------

def test_aggregator_buy_on_bullish_consensus() -> None:
    from libs.llm_analyst.agents import AgentReport
    agg = DecisionAggregator()
    reports = {
        "TechnicalAnalyst": AgentReport("TechnicalAnalyst", AnalystView.BULLISH, 0.8, "ok"),
        "NewsAnalyst": AgentReport("NewsAnalyst", AnalystView.BULLISH, 0.75, "ok"),
        "FundamentalAnalyst": AgentReport("FundamentalAnalyst", AnalystView.BULLISH, 0.6, "ok"),
        "RiskOfficer": AgentReport("RiskOfficer", AnalystView.BULLISH, 0.7, "ok", data_used={"approved": True}),
    }
    result = agg.aggregate("600519.SH", reports)
    assert result.action == RecommendationAction.BUY
    assert result.approved is True


def test_aggregator_hold_on_risk_veto() -> None:
    from libs.llm_analyst.agents import AgentReport
    agg = DecisionAggregator()
    reports = {
        "TechnicalAnalyst": AgentReport("TechnicalAnalyst", AnalystView.BULLISH, 0.8, "ok"),
        "NewsAnalyst": AgentReport("NewsAnalyst", AnalystView.BULLISH, 0.7, "ok"),
        "FundamentalAnalyst": AgentReport("FundamentalAnalyst", AnalystView.BULLISH, 0.6, "ok"),
        "RiskOfficer": AgentReport(
            "RiskOfficer", AnalystView.BEARISH, 0.9, "ST blocked",
            data_used={"approved": False}
        ),
    }
    result = agg.aggregate("600519.SH", reports)
    assert result.action == RecommendationAction.HOLD
    assert result.approved is False


def test_aggregator_sell_on_bearish_consensus() -> None:
    from libs.llm_analyst.agents import AgentReport
    agg = DecisionAggregator()
    reports = {
        "TechnicalAnalyst": AgentReport("TechnicalAnalyst", AnalystView.BEARISH, 0.75, "ok"),
        "NewsAnalyst": AgentReport("NewsAnalyst", AnalystView.BEARISH, 0.8, "ok"),
        "FundamentalAnalyst": AgentReport("FundamentalAnalyst", AnalystView.BEARISH, 0.65, "ok"),
        "RiskOfficer": AgentReport("RiskOfficer", AnalystView.BEARISH, 0.7, "ok", data_used={"approved": True}),
    }
    result = agg.aggregate("600519.SH", reports)
    assert result.action == RecommendationAction.SELL


# ---------------------------------------------------------------------------
# AnalysisOrchestrator end-to-end
# ---------------------------------------------------------------------------

def test_orchestrator_returns_valid_report() -> None:
    orch = AnalysisOrchestrator()
    report = orch.analyze(
        symbol="600519.SH",
        features=_make_features(),
        signal_score=0.45,
        signal_conf=0.68,
        instrument=_good_instrument(),
        news_items=[{"sentiment_score": 0.5, "summary": "利好消息", "event_type": "EARNINGS"}],
        risk_flags=[],
    )
    assert report.symbol == "600519.SH"
    assert report.action in {RecommendationAction.BUY, RecommendationAction.HOLD, RecommendationAction.SELL}
    assert 0.0 <= report.confidence <= 1.0
    assert report.summary
    assert report.reasoning
    assert report.llm_powered is False  # keyword mode


def test_orchestrator_reports_components() -> None:
    orch = AnalysisOrchestrator()
    report = orch.analyze("600519.SH", _make_features(), 0.4, 0.6, _good_instrument(), [], [])
    assert "TechnicalAnalyst" in report.components
    assert "NewsAnalyst" in report.components
    assert "FundamentalAnalyst" in report.components
    assert "RiskOfficer" in report.components
    assert "weighted_score" in report.components


def test_orchestrator_st_stock_always_hold_or_sell() -> None:
    orch = AnalysisOrchestrator()
    report = orch.analyze("600519.SH", _make_features(), 0.9, 0.9, _st_instrument(), [], ["ST_STOCK"])
    assert report.action in {RecommendationAction.HOLD, RecommendationAction.SELL}
    assert report.approved is False
