"""Unit tests for NewsService."""

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from apps.api.app.services.news_service import NewsService


_PUB_TIME = datetime(2026, 4, 25, 9, 0, 0)
_UNIQUE_TEXT = "贵州茅台2026年一季度营收同比增长15%，超市场预期。" + "x" * 80


def test_ingest_article_stores_record(db_session: Session) -> None:
    svc = NewsService(db_session)
    article = svc.ingest_article(
        source="test",
        title="茅台业绩超预期",
        raw_text=_UNIQUE_TEXT,
        published_at=_PUB_TIME,
        symbols=["600519.SH"],
    )
    assert article.article_id is not None
    assert article.content_hash != ""
    assert "600519.SH" in article.symbols


def test_ingest_duplicate_raises(db_session: Session) -> None:
    svc = NewsService(db_session)
    svc.ingest_article("src", "title", _UNIQUE_TEXT, _PUB_TIME, [])
    with pytest.raises(ValueError, match="Duplicate article"):
        svc.ingest_article("src", "title2", _UNIQUE_TEXT, _PUB_TIME, [])


def test_list_articles_all(db_session: Session) -> None:
    svc = NewsService(db_session)
    svc.ingest_article("s1", "t1", "content one aaa" * 5, _PUB_TIME, ["600519.SH"])
    svc.ingest_article("s2", "t2", "content two bbb" * 5, _PUB_TIME, ["300750.SZ"])
    articles = svc.list_articles(limit=10)
    assert len(articles) == 2


def test_list_articles_filtered_by_symbol(db_session: Session) -> None:
    svc = NewsService(db_session)
    svc.ingest_article("s1", "t1", "aaaa content one" * 5, _PUB_TIME, ["600519.SH"])
    svc.ingest_article("s2", "t2", "bbbb content two" * 5, _PUB_TIME, ["300750.SZ"])
    articles = svc.list_articles(symbol="600519.SH", limit=10)
    assert len(articles) == 1
    assert articles[0].symbols == ["600519.SH"]


def test_add_event_and_retrieve(db_session: Session) -> None:
    svc = NewsService(db_session)
    article = svc.ingest_article("src", "title", "event test text ccc" * 5, _PUB_TIME, ["300750.SZ"])
    event = svc.add_event(
        article_id=article.article_id,
        event_type="EARNINGS_BEAT",
        sentiment_score=0.8,
        urgency_score=0.7,
        relevance_score=0.9,
        summary="strong earnings",
    )
    assert event.event_id is not None
    assert event.event_type == "EARNINGS_BEAT"
    assert event.sentiment_score == 0.8


def test_list_events_for_symbol(db_session: Session) -> None:
    svc = NewsService(db_session)
    article = svc.ingest_article(
        "src", "t", "list events test ddd" * 5, _PUB_TIME, ["000001.SZ"],
        auto_analyze=False,
    )
    svc.add_event(article.article_id, "NEWS_NEGATIVE", -0.5, 0.6, 0.8, "bad news")
    events = svc.list_events_for_symbol("000001.SZ", limit=10)
    assert len(events) == 1
    assert events[0].sentiment_score == -0.5


def test_ingest_auto_creates_event(db_session: Session) -> None:
    """auto_analyze=True (default) should produce a NewsEvent automatically."""
    svc = NewsService(db_session)
    article = svc.ingest_article(
        "src", "贵州茅台业绩超预期", "贵州茅台 Q1 营收同比增长 15%，盈利创新高，业绩超出预期。" * 3,
        _PUB_TIME, ["600519.SH"],
    )
    events = svc.list_events_for_symbol("600519.SH", limit=10)
    assert len(events) == 1
    # Positive keywords ("增长","盈利","创新","超预期","业绩") should drive sentiment > 0
    assert events[0].sentiment_score > 0


def test_list_events_for_symbol_no_match(db_session: Session) -> None:
    svc = NewsService(db_session)
    events = svc.list_events_for_symbol("NONE.XX", limit=10)
    assert events == []


def test_ingest_article_with_url(db_session: Session) -> None:
    svc = NewsService(db_session)
    article = svc.ingest_article(
        source="eastmoney",
        title="url test",
        raw_text="url test content eee" * 5,
        published_at=_PUB_TIME,
        symbols=[],
        url="https://example.com/news/1",
    )
    assert article.url == "https://example.com/news/1"
