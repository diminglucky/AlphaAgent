"""Tests for news analyzer."""

from datetime import datetime

import pytest

from libs.llm_analyst.analyzer import (
    EventType,
    NewsAnalyzer,
    NewsArticle,
    SentimentType,
)


def test_news_analyzer_initialization():
    """Test analyzer initializes correctly."""
    analyzer = NewsAnalyzer(use_llm=False)
    
    assert analyzer.use_llm is False
    assert len(analyzer.positive_keywords) > 0
    assert len(analyzer.negative_keywords) > 0


def test_analyze_positive_news():
    """Test analysis of positive news."""
    analyzer = NewsAnalyzer(use_llm=False)
    
    article = NewsArticle(
        article_id="news1",
        source="test",
        title="公司业绩大幅增长，盈利超预期",
        content="该公司发布年报，营收和利润均实现大幅增长，超出市场预期。",
        published_at=datetime.now(),
        symbols=["600519.SH"],
    )
    
    analysis = analyzer.analyze(article)
    
    assert analysis.sentiment in (SentimentType.POSITIVE, SentimentType.VERY_POSITIVE)
    assert analysis.sentiment_score > 0
    assert len(analysis.affected_symbols) > 0


def test_analyze_negative_news():
    """Test analysis of negative news."""
    analyzer = NewsAnalyzer(use_llm=False)
    
    article = NewsArticle(
        article_id="news2",
        source="test",
        title="公司遭监管调查，股价大幅下跌",
        content="该公司因涉嫌违规被监管部门立案调查，股价今日大幅下跌，投资者面临重大风险。",
        published_at=datetime.now(),
        symbols=["000001.SZ"],
    )
    
    analysis = analyzer.analyze(article)
    
    assert analysis.sentiment in (SentimentType.NEGATIVE, SentimentType.VERY_NEGATIVE)
    assert analysis.sentiment_score < 0
    assert len(analysis.risk_factors) > 0


def test_detect_event_type():
    """Test event type detection."""
    analyzer = NewsAnalyzer(use_llm=False)
    
    # Earnings event
    text = "公司发布财报，业绩超预期"
    event_type = analyzer._detect_event_type(text)
    assert event_type == EventType.EARNINGS
    
    # Regulatory event
    text = "公司遭监管处罚"
    event_type = analyzer._detect_event_type(text)
    assert event_type == EventType.REGULATORY
    
    # M&A event
    text = "公司宣布收购竞争对手"
    event_type = analyzer._detect_event_type(text)
    assert event_type == EventType.MERGER_ACQUISITION


def test_batch_analyze():
    """Test batch analysis."""
    analyzer = NewsAnalyzer(use_llm=False)
    
    articles = [
        NewsArticle(
            article_id=f"news{i}",
            source="test",
            title=f"新闻标题{i}",
            content="公司业绩增长",
            published_at=datetime.now(),
        )
        for i in range(3)
    ]
    
    analyses = analyzer.batch_analyze(articles)
    
    assert len(analyses) == 3
    assert all(a.sentiment_score > 0 for a in analyses)


def test_filter_by_sentiment():
    """Test filtering by sentiment."""
    analyzer = NewsAnalyzer(use_llm=False)
    
    articles = [
        NewsArticle(
            article_id="news1",
            source="test",
            title="利好消息",
            content="公司业绩大幅增长",
            published_at=datetime.now(),
        ),
        NewsArticle(
            article_id="news2",
            source="test",
            title="利空消息",
            content="公司遭遇重大亏损",
            published_at=datetime.now(),
        ),
    ]
    
    analyses = analyzer.batch_analyze(articles)
    positive = analyzer.filter_by_sentiment(analyses, min_score=0.0)
    
    assert len(positive) < len(analyses)
    assert all(a.sentiment_score >= 0.0 for a in positive)
