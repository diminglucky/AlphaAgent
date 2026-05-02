"""LLM-based news and event analyzer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SentimentType(str, Enum):
    """Sentiment classification."""
    VERY_POSITIVE = "VERY_POSITIVE"
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    VERY_NEGATIVE = "VERY_NEGATIVE"


class EventType(str, Enum):
    """News event types."""
    EARNINGS = "EARNINGS"
    MERGER_ACQUISITION = "MERGER_ACQUISITION"
    REGULATORY = "REGULATORY"
    PRODUCT_LAUNCH = "PRODUCT_LAUNCH"
    MANAGEMENT_CHANGE = "MANAGEMENT_CHANGE"
    MARKET_RUMOR = "MARKET_RUMOR"
    INDUSTRY_NEWS = "INDUSTRY_NEWS"
    MACRO_ECONOMIC = "MACRO_ECONOMIC"
    OTHER = "OTHER"


@dataclass(frozen=True)
class NewsArticle:
    """News article data."""
    article_id: str
    source: str
    title: str
    content: str
    published_at: datetime
    url: Optional[str] = None
    symbols: list[str] = None


@dataclass(frozen=True)
class NewsAnalysis:
    """Analysis result for a news article."""
    article_id: str
    sentiment: SentimentType
    sentiment_score: float  # -1.0 to 1.0
    event_type: EventType
    urgency_score: float  # 0.0 to 1.0
    relevance_score: float  # 0.0 to 1.0
    summary: str
    key_points: list[str]
    risk_factors: list[str]
    affected_symbols: list[str]
    reasoning: str


class NewsAnalyzer:
    """Analyze news articles for trading signals."""
    
    def __init__(self, use_llm: bool = False) -> None:
        """
        Initialize news analyzer.
        
        Args:
            use_llm: Whether to use LLM for analysis (requires API key)
        """
        self.use_llm = use_llm
        
        # Keyword-based sentiment analysis (fallback)
        self.positive_keywords = {
            "增长", "上涨", "盈利", "突破", "创新", "领先", "优势",
            "扩张", "收购", "合作", "订单", "业绩", "超预期", "利好"
        }
        
        self.negative_keywords = {
            "下跌", "亏损", "风险", "调查", "处罚", "违规", "裁员",
            "退市", "暂停", "延期", "取消", "减持", "预警", "利空"
        }
    
    def analyze(self, article: NewsArticle) -> NewsAnalysis:
        """
        Analyze a news article.
        
        Args:
            article: News article to analyze
            
        Returns:
            Analysis result
        """
        if self.use_llm:
            return self._analyze_with_llm(article)
        else:
            return self._analyze_with_keywords(article)
    
    def _analyze_with_keywords(self, article: NewsArticle) -> NewsAnalysis:
        """Keyword-based analysis (fallback method)."""
        text = f"{article.title} {article.content}".lower()
        
        # Count sentiment keywords
        positive_count = sum(1 for kw in self.positive_keywords if kw in text)
        negative_count = sum(1 for kw in self.negative_keywords if kw in text)
        
        # Calculate sentiment score
        total_count = positive_count + negative_count
        if total_count == 0:
            sentiment_score = 0.0
            sentiment = SentimentType.NEUTRAL
        else:
            sentiment_score = (positive_count - negative_count) / total_count
            if sentiment_score > 0.5:
                sentiment = SentimentType.VERY_POSITIVE
            elif sentiment_score > 0.2:
                sentiment = SentimentType.POSITIVE
            elif sentiment_score < -0.5:
                sentiment = SentimentType.VERY_NEGATIVE
            elif sentiment_score < -0.2:
                sentiment = SentimentType.NEGATIVE
            else:
                sentiment = SentimentType.NEUTRAL
        
        # Detect event type
        event_type = self._detect_event_type(text)
        
        # Calculate urgency (based on keywords and recency)
        urgency_keywords = {"紧急", "重大", "突发", "立即", "警告"}
        urgency_score = min(1.0, sum(1 for kw in urgency_keywords if kw in text) * 0.3)
        
        # Relevance score (simplified)
        relevance_score = 0.8 if article.symbols else 0.5
        
        # Extract key points (first 3 sentences)
        sentences = article.content.split("。")[:3]
        key_points = [s.strip() + "。" for s in sentences if s.strip()]
        
        # Extract risk factors
        risk_factors = []
        if negative_count > 0:
            risk_factors.append("新闻包含负面关键词")
        if "风险" in text:
            risk_factors.append("明确提及风险")
        
        return NewsAnalysis(
            article_id=article.article_id,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            event_type=event_type,
            urgency_score=urgency_score,
            relevance_score=relevance_score,
            summary=article.title,
            key_points=key_points,
            risk_factors=risk_factors,
            affected_symbols=article.symbols or [],
            reasoning=f"基于关键词分析: 正面词{positive_count}个, 负面词{negative_count}个",
        )
    
    def _detect_event_type(self, text: str) -> EventType:
        """Detect event type from text."""
        if any(kw in text for kw in ["业绩", "财报", "盈利", "营收"]):
            return EventType.EARNINGS
        elif any(kw in text for kw in ["收购", "并购", "重组"]):
            return EventType.MERGER_ACQUISITION
        elif any(kw in text for kw in ["监管", "处罚", "调查", "违规"]):
            return EventType.REGULATORY
        elif any(kw in text for kw in ["产品", "发布", "上市"]):
            return EventType.PRODUCT_LAUNCH
        elif any(kw in text for kw in ["董事", "高管", "任命", "辞职"]):
            return EventType.MANAGEMENT_CHANGE
        elif any(kw in text for kw in ["传闻", "消息", "据悉"]):
            return EventType.MARKET_RUMOR
        elif any(kw in text for kw in ["行业", "板块", "赛道"]):
            return EventType.INDUSTRY_NEWS
        elif any(kw in text for kw in ["经济", "政策", "央行", "gdp"]):
            return EventType.MACRO_ECONOMIC
        else:
            return EventType.OTHER
    
    def _analyze_with_llm(self, article: NewsArticle) -> NewsAnalysis:
        """LLM-based analysis via LLMClient.chat_json.

        Falls back to keyword analysis when:
          - No LLM is configured (QUANT_LLM_PROVIDER=keyword or no API key)
          - The LLM returns malformed / empty JSON
        """
        from libs.llm_analyst.llm_client import LLMClient

        client = LLMClient()
        if not client.is_llm_available():
            return self._analyze_with_keywords(article)

        system_prompt = (
            "你是一名专业的A股股票新闻分析师。请对给定的新闻进行分析，"
            "并以纯JSON格式输出分析结果，字段如下：\n"
            "- sentiment: 情绪类型 (VERY_POSITIVE/POSITIVE/NEUTRAL/NEGATIVE/VERY_NEGATIVE)\n"
            "- sentiment_score: 情绪分数 (-1.0到1.0)\n"
            "- event_type: 事件类型 (EARNINGS/MERGER_ACQUISITION/REGULATORY/"
            "PRODUCT_LAUNCH/MANAGEMENT_CHANGE/MARKET_RUMOR/INDUSTRY_NEWS/MACRO_ECONOMIC/OTHER)\n"
            "- urgency_score: 紧急程度 (0.0到1.0)\n"
            "- relevance_score: 相关性 (0.0到1.0)\n"
            "- summary: 一句话摘要\n"
            "- key_points: 关键点列表 (最多3个字符串)\n"
            "- risk_factors: 风险因素列表\n"
            "- affected_symbols: 受影响的股票代码列表\n"
            "- reasoning: 分析推理过程\n"
            "只输出JSON，不要其他内容。"
        )
        symbols_hint = f"\n相关股票: {', '.join(article.symbols)}" if article.symbols else ""
        user_prompt = (
            f"新闻标题：{article.title}\n\n"
            f"新闻内容：{article.content}"
            f"{symbols_hint}"
        )

        data = client.chat_json(system_prompt, user_prompt)
        if not data:
            return self._analyze_with_keywords(article)

        try:
            raw_sentiment = data.get("sentiment", "NEUTRAL").upper()
            sentiment = SentimentType(raw_sentiment) if raw_sentiment in SentimentType._value2member_map_ else SentimentType.NEUTRAL
            raw_event = data.get("event_type", "OTHER").upper()
            event_type = EventType(raw_event) if raw_event in EventType._value2member_map_ else EventType.OTHER
            return NewsAnalysis(
                article_id=article.article_id,
                sentiment=sentiment,
                sentiment_score=float(data.get("sentiment_score", 0.0)),
                event_type=event_type,
                urgency_score=float(data.get("urgency_score", 0.0)),
                relevance_score=float(data.get("relevance_score", 0.5)),
                summary=str(data.get("summary", article.title)),
                key_points=list(data.get("key_points", [])),
                risk_factors=list(data.get("risk_factors", [])),
                affected_symbols=list(data.get("affected_symbols", article.symbols or [])),
                reasoning=str(data.get("reasoning", "")),
            )
        except (KeyError, ValueError, TypeError):
            return self._analyze_with_keywords(article)
    
    def batch_analyze(self, articles: list[NewsArticle]) -> list[NewsAnalysis]:
        """Analyze multiple articles."""
        return [self.analyze(article) for article in articles]
    
    def filter_by_sentiment(
        self,
        analyses: list[NewsAnalysis],
        min_score: float = 0.0,
    ) -> list[NewsAnalysis]:
        """Filter analyses by sentiment score."""
        return [a for a in analyses if a.sentiment_score >= min_score]
    
    def filter_by_relevance(
        self,
        analyses: list[NewsAnalysis],
        min_relevance: float = 0.5,
    ) -> list[NewsAnalysis]:
        """Filter analyses by relevance score."""
        return [a for a in analyses if a.relevance_score >= min_relevance]
