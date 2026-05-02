"""Unit tests for pipelines: backfill, intraday, news collector."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pipelines.backfill.daily_bars import DailyBarBackfillPipeline
from pipelines.intraday.realtime_updater import RealtimeUpdater, TradingSessionManager
from pipelines.news.collector import NewsCollector, MockNewsSource, run_news_collection_pipeline
from libs.quant_core.models import Instrument


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_provider(bars=None, quotes=None):
    provider = MagicMock()
    provider.get_bars.return_value = bars or []
    provider.get_realtime_quotes.return_value = quotes or []
    return provider


def _instrument(symbol: str = "600519.SH") -> Instrument:
    return Instrument(
        symbol=symbol, exchange="SH", name="贵州茅台",
        industry="白酒", list_date=date(2001, 8, 27),
        delist_date=None, status="listed", is_st=False,
    )


# ---------------------------------------------------------------------------
# DailyBarBackfillPipeline
# ---------------------------------------------------------------------------

class TestDailyBarBackfillPipeline:
    def test_backfill_symbol_calls_provider(self):
        from libs.quant_core.models import MarketBar
        bar = MarketBar(
            symbol="600519.SH", trade_date=date(2026, 4, 1),
            open=1700.0, high=1720.0, low=1695.0, close=1710.0,
            volume=30000, amount=5e7, turnover_rate=0.20,
            adj_type="qfq", data_source="mock",
        )
        provider = _mock_provider(bars=[bar])
        pipeline = DailyBarBackfillPipeline(provider)

        result = pipeline.backfill_symbol(
            "600519.SH",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 25),
        )

        provider.get_bars.assert_called_once_with(
            symbol="600519.SH", freq="1d",
            start=date(2026, 4, 1), end=date(2026, 4, 25),
        )
        assert result == [bar]

    def test_backfill_symbol_error_returns_empty(self):
        provider = _mock_provider()
        provider.get_bars.side_effect = RuntimeError("source down")
        pipeline = DailyBarBackfillPipeline(provider)

        result = pipeline.backfill_symbol("600519.SH", start_date=date(2026, 1, 1))
        assert result == []

    def test_backfill_all_instruments_aggregates(self):
        from libs.quant_core.models import MarketBar
        bar = MarketBar(
            symbol="000001.SZ", trade_date=date(2026, 4, 1),
            open=11.0, high=11.5, low=10.9, close=11.2,
            volume=1_000_000, amount=1.2e7, turnover_rate=0.5,
            adj_type="qfq", data_source="mock",
        )
        provider = _mock_provider(bars=[bar])
        pipeline = DailyBarBackfillPipeline(provider)
        instruments = [_instrument("000001.SZ"), _instrument("300750.SZ")]

        results = pipeline.backfill_all_instruments(instruments, start_date=date(2026, 1, 1))
        assert "000001.SZ" in results
        assert "300750.SZ" in results

    def test_backfill_all_instruments_skips_empty_symbols(self):
        provider = _mock_provider(bars=[])
        pipeline = DailyBarBackfillPipeline(provider)

        results = pipeline.backfill_all_instruments(
            [_instrument("600519.SH")], start_date=date(2026, 1, 1),
        )
        assert "600519.SH" not in results

    def test_incremental_update_uses_lookback_window(self):
        provider = _mock_provider(bars=[])
        pipeline = DailyBarBackfillPipeline(provider)

        pipeline.incremental_update(["600519.SH"], lookback_days=7)

        call_kwargs = provider.get_bars.call_args[1]
        diff = (call_kwargs["end"] - call_kwargs["start"]).days
        assert diff >= 7


# ---------------------------------------------------------------------------
# RealtimeUpdater
# ---------------------------------------------------------------------------

class TestRealtimeUpdater:
    def test_add_remove_symbols(self):
        updater = RealtimeUpdater(_mock_provider())
        updater.add_symbols(["600519.SH", "000001.SZ"])
        assert len(updater.watchlist) == 2
        updater.remove_symbols(["000001.SZ"])
        assert updater.watchlist == ["600519.SH"]

    def test_add_symbol_no_duplicate(self):
        updater = RealtimeUpdater(_mock_provider())
        updater.add_symbols(["600519.SH"])
        updater.add_symbols(["600519.SH"])
        assert updater.watchlist.count("600519.SH") == 1

    def test_get_latest_quotes_empty_watchlist(self):
        updater = RealtimeUpdater(_mock_provider())
        assert updater.get_latest_quotes() == []

    def test_get_latest_quotes_calls_provider(self):
        from libs.quant_core.models import RealtimeQuote
        quote = RealtimeQuote(
            symbol="600519.SH", quote_time=datetime.now(),
            last_price=1719.0, bid1=1718.5, ask1=1719.5,
            volume=30000, turnover=5.1e7, pct_change=0.1,
            limit_up=1889.0, limit_down=1545.0,
        )
        provider = _mock_provider(quotes=[quote])
        updater = RealtimeUpdater(provider)
        updater.add_symbols(["600519.SH"])

        result = updater.get_latest_quotes()
        assert result == [quote]

    def test_register_callback(self):
        provider = _mock_provider()
        updater = RealtimeUpdater(provider)
        cb = MagicMock()
        updater.register_callback(cb)
        assert cb in updater.callbacks

    def test_stop_sets_flag(self):
        updater = RealtimeUpdater(_mock_provider())
        updater.is_running = True
        updater.stop()
        assert updater.is_running is False


# ---------------------------------------------------------------------------
# TradingSessionManager
# ---------------------------------------------------------------------------

class TestTradingSessionManager:
    def _dt(self, hour: int, minute: int, weekday: int = 0) -> datetime:
        base = datetime(2026, 4, 28)  # Tuesday
        delta = weekday - base.weekday()
        d = base + timedelta(days=delta)
        return d.replace(hour=hour, minute=minute, second=0)

    def test_morning_session_is_trading(self):
        assert TradingSessionManager.is_trading_time(self._dt(10, 0)) is True

    def test_afternoon_session_is_trading(self):
        assert TradingSessionManager.is_trading_time(self._dt(14, 0)) is True

    def test_lunch_break_not_trading(self):
        assert TradingSessionManager.is_trading_time(self._dt(12, 0)) is False

    def test_after_close_not_trading(self):
        assert TradingSessionManager.is_trading_time(self._dt(15, 30)) is False

    def test_weekend_not_trading(self):
        saturday = datetime(2026, 4, 25, 10, 0)  # Saturday
        assert TradingSessionManager.is_trading_time(saturday) is False

    def test_get_session_status_morning(self):
        assert TradingSessionManager.get_session_status(self._dt(9, 45)) == "MORNING_SESSION"

    def test_get_session_status_afternoon(self):
        assert TradingSessionManager.get_session_status(self._dt(14, 30)) == "AFTERNOON_SESSION"

    def test_get_session_status_lunch(self):
        assert TradingSessionManager.get_session_status(self._dt(12, 0)) == "LUNCH_BREAK"

    def test_get_session_status_pre_market(self):
        assert TradingSessionManager.get_session_status(self._dt(8, 0)) == "PRE_MARKET"

    def test_get_session_status_after_market(self):
        assert TradingSessionManager.get_session_status(self._dt(16, 0)) == "AFTER_MARKET"

    def test_get_session_status_weekend(self):
        saturday = datetime(2026, 4, 25, 10, 0)
        assert TradingSessionManager.get_session_status(saturday) == "WEEKEND"


# ---------------------------------------------------------------------------
# NewsCollector
# ---------------------------------------------------------------------------

class TestNewsCollector:
    def test_collect_article_returns_article(self):
        collector = NewsCollector()
        article = collector.collect_article(
            source="test", title="茅台业绩增长", content="净利润同比增长15%",
            symbols=["600519.SH"],
        )
        assert article is not None
        assert article.title == "茅台业绩增长"
        assert "600519.SH" in article.symbols

    def test_collect_duplicate_returns_none(self):
        collector = NewsCollector()
        collector.collect_article(source="s", title="A", content="same content")
        result = collector.collect_article(source="s", title="B", content="same content")
        assert result is None

    def test_get_articles_filter_by_symbol(self):
        collector = NewsCollector()
        collector.collect_article("s", "t1", "c1", symbols=["600519.SH"])
        collector.collect_article("s", "t2", "c2", symbols=["000001.SZ"])

        result = collector.get_articles(symbol="600519.SH")
        assert len(result) == 1
        assert result[0].title == "t1"

    def test_get_articles_filter_by_source(self):
        collector = NewsCollector()
        collector.collect_article("akshare", "t1", "content1")
        collector.collect_article("ths", "t2", "content2")

        result = collector.get_articles(source="akshare")
        assert len(result) == 1

    def test_get_articles_filter_by_since(self):
        collector = NewsCollector()
        old_time = datetime(2026, 1, 1)
        new_time = datetime(2026, 4, 28)
        collector.collect_article("s", "old", "old content", published_at=old_time)
        collector.collect_article("s", "new", "new content", published_at=new_time)

        result = collector.get_articles(since=datetime(2026, 4, 1))
        assert len(result) == 1
        assert result[0].title == "new"

    def test_clear_old_articles(self):
        collector = NewsCollector()
        old_time = datetime(2026, 1, 1)
        new_time = datetime.now()
        collector.collect_article("s", "old", "old stuff", published_at=old_time)
        collector.collect_article("s", "new", "new stuff", published_at=new_time)

        removed = collector.clear_old_articles(days=30)
        assert removed == 1
        assert len(collector.collected_articles) == 1

    def test_articles_sorted_newest_first(self):
        collector = NewsCollector()
        early = datetime(2026, 4, 1)
        late = datetime(2026, 4, 28)
        collector.collect_article("s", "A", "content A", published_at=early)
        collector.collect_article("s", "B", "content B", published_at=late)

        articles = collector.get_articles()
        assert articles[0].title == "B"

    def test_run_pipeline_returns_count(self):
        collector = NewsCollector()
        count = run_news_collection_pipeline(collector)
        assert count == 3  # MockNewsSource has 3 sample articles

    def test_run_pipeline_deduplication(self):
        collector = NewsCollector()
        count1 = run_news_collection_pipeline(collector)
        count2 = run_news_collection_pipeline(collector)
        assert count1 == 3
        assert count2 == 0  # all already collected


# ---------------------------------------------------------------------------
# MockNewsSource
# ---------------------------------------------------------------------------

def test_mock_news_source_fetch_latest():
    source = MockNewsSource()
    articles = source.fetch_latest(limit=2)
    assert len(articles) == 2
    assert "title" in articles[0]
    assert "content" in articles[0]
    assert "symbols" in articles[0]
