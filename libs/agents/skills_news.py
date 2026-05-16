"""News skills — 使用 market_service 获取新闻"""
from __future__ import annotations

from libs.agents.skills import Skill, SkillRegistry


def register_news_skills(reg: SkillRegistry) -> None:
    from apps.api.app.services import market_service

    def _search_news(symbol: str, days: int = 7, _db=None) -> dict:
        """获取个股近期新闻"""
        news = market_service.get_stock_news(symbol, count=15)
        return {
            "symbol": symbol,
            "count": len(news),
            "articles": news[:10],
        }

    def _summarize_sentiment(symbol: str, days: int = 7, _db=None) -> dict:
        """简单情绪分析（基于新闻标题关键词）"""
        news = market_service.get_stock_news(symbol, count=15)
        if not news:
            return {"symbol": symbol, "count": 0, "avg_sentiment": 0, "max_urgency": 0, "negative_events": []}

        # 简单关键词情绪判断
        positive_kw = ["增长", "盈利", "利好", "突破", "新高", "合作", "中标", "获批", "分红", "回购", "上涨", "涨停"]
        negative_kw = ["亏损", "下滑", "利空", "跌停", "违规", "处罚", "诉讼", "减持", "质押", "风险", "下跌", "暴跌"]

        scores = []
        negative_events = []
        for n in news:
            title = n.get("title", "")
            pos = sum(1 for kw in positive_kw if kw in title)
            neg = sum(1 for kw in negative_kw if kw in title)
            score = (pos - neg) / max(pos + neg, 1) if (pos + neg) > 0 else 0
            scores.append(score)
            if score < -0.3:
                negative_events.append({"title": title, "sentiment": round(score, 2), "time": n.get("time", "")})

        avg_sent = round(sum(scores) / len(scores), 3) if scores else 0
        max_urgency = max(abs(s) for s in scores) if scores else 0

        return {
            "symbol": symbol,
            "count": len(news),
            "avg_sentiment": avg_sent,
            "max_urgency": round(max_urgency, 3),
            "negative_events_count": len(negative_events),
            "top_negative": negative_events[:3],
            "sentiment_label": "正面" if avg_sent > 0.1 else "负面" if avg_sent < -0.1 else "中性",
        }

    reg.register_many([
        Skill(
            name="search_news",
            description="获取某只股票近期相关新闻（标题、来源、时间、链接）。Agent 用于了解最新动态和公司事件。",
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
        ),
        Skill(
            name="analyze_news_sentiment",
            description="分析某只股票近期新闻的情绪倾向（正面/负面/中性），返回情绪均值、负面事件列表。",
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
        ),
    ])
