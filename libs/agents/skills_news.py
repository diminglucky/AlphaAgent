"""News & event skills."""

from __future__ import annotations

from datetime import datetime, timedelta
from libs.agents.skills import Skill, SkillRegistry


def register_news_skills(reg: SkillRegistry) -> None:

    def _search_news(symbol: str, days: int = 7, _db=None) -> dict:
        if _db is None:
            return {"error": "no db"}
        from apps.api.app.db.repositories import NewsRepository
        articles = NewsRepository(_db).list_articles(symbol=symbol, limit=20)
        cutoff = datetime.now() - timedelta(days=days)
        articles = [a for a in articles if a.published_at >= cutoff]
        return {
            "symbol": symbol,
            "count": len(articles),
            "articles": [
                {"title": a.title, "source": a.source,
                 "published_at": a.published_at.isoformat(),
                 "url": a.url}
                for a in articles[:10]
            ],
        }

    def _summarize_sentiment(symbol: str, days: int = 7, _db=None) -> dict:
        if _db is None:
            return {"error": "no db"}
        from apps.api.app.db.repositories import NewsRepository
        events = NewsRepository(_db).list_events_for_symbol(symbol, limit=30)
        cutoff = datetime.now() - timedelta(days=days)
        events = [e for e in events if e.created_at >= cutoff]
        if not events:
            return {"symbol": symbol, "count": 0, "avg_sentiment": 0,
                    "max_urgency": 0, "negative_events": []}
        avg = sum(e.sentiment_score for e in events) / len(events)
        max_urg = max((e.urgency_score for e in events), default=0)
        negatives = [
            {"event_type": e.event_type, "summary": e.summary,
             "sentiment": e.sentiment_score, "urgency": e.urgency_score}
            for e in events if e.sentiment_score < -0.3
        ]
        return {
            "symbol": symbol,
            "count": len(events),
            "avg_sentiment": round(avg, 3),
            "max_urgency": round(max_urg, 3),
            "negative_events_count": len(negatives),
            "top_negative": negatives[:3],
        }

    reg.register_many([
        Skill(
            name="search_news",
            description="搜索某只股票最近 N 天的相关新闻文章。返回标题、来源、时间。Agent 用于了解最新动态。",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "days": {"type": "integer", "default": 7},
                },
                "required": ["symbol"],
            },
            handler=_search_news,
            category="news",
            requires_db=True,
        ),
        Skill(
            name="analyze_news_sentiment",
            description="汇总某只股票最近 N 天的新闻事件情绪分（[-1, +1]）、紧急度、负面事件清单。Agent 用于风险评估。",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "days": {"type": "integer", "default": 7},
                },
                "required": ["symbol"],
            },
            handler=_summarize_sentiment,
            category="news",
            requires_db=True,
        ),
    ])
