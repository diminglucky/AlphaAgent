"""News collection pipeline."""

import hashlib
import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from libs.llm_analyst.analyzer import NewsArticle


logger = logging.getLogger(__name__)


class NewsCollector:
    """Collect news articles from various sources."""
    
    def __init__(self) -> None:
        self.collected_articles: dict[str, NewsArticle] = {}
        self.content_hashes: set[str] = set()
    
    def _calculate_content_hash(self, content: str) -> str:
        """Calculate content hash for deduplication."""
        return hashlib.md5(content.encode()).hexdigest()
    
    def _is_duplicate(self, content: str) -> bool:
        """Check if content is duplicate."""
        content_hash = self._calculate_content_hash(content)
        return content_hash in self.content_hashes
    
    def collect_article(
        self,
        source: str,
        title: str,
        content: str,
        published_at: Optional[datetime] = None,
        url: Optional[str] = None,
        symbols: Optional[list[str]] = None,
    ) -> Optional[NewsArticle]:
        """
        Collect a news article.
        
        Args:
            source: News source
            title: Article title
            content: Article content
            published_at: Publication time
            url: Article URL
            symbols: Related stock symbols
            
        Returns:
            NewsArticle if collected, None if duplicate
        """
        # Check for duplicates
        if self._is_duplicate(content):
            logger.debug(f"Duplicate article skipped: {title}")
            return None
        
        # Create article
        article_id = f"NEWS-{uuid4().hex[:12]}"
        article = NewsArticle(
            article_id=article_id,
            source=source,
            title=title,
            content=content,
            published_at=published_at or datetime.now(),
            url=url,
            symbols=symbols or [],
        )
        
        # Store article
        self.collected_articles[article_id] = article
        self.content_hashes.add(self._calculate_content_hash(content))
        
        logger.info(f"Collected article: {article_id} - {title}")
        return article
    
    def get_articles(
        self,
        source: Optional[str] = None,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[NewsArticle]:
        """
        Get collected articles with filters.
        
        Args:
            source: Filter by source
            symbol: Filter by related symbol
            since: Filter by publication time
            
        Returns:
            Filtered articles
        """
        articles = list(self.collected_articles.values())
        
        if source:
            articles = [a for a in articles if a.source == source]
        
        if symbol:
            articles = [a for a in articles if symbol in (a.symbols or [])]
        
        if since:
            articles = [a for a in articles if a.published_at >= since]
        
        return sorted(articles, key=lambda a: a.published_at, reverse=True)
    
    def clear_old_articles(self, days: int = 30) -> int:
        """
        Clear articles older than specified days.
        
        Args:
            days: Number of days to keep
            
        Returns:
            Number of articles removed
        """
        cutoff = datetime.now().timestamp() - (days * 24 * 3600)
        
        to_remove = [
            article_id
            for article_id, article in self.collected_articles.items()
            if article.published_at.timestamp() < cutoff
        ]
        
        for article_id in to_remove:
            article = self.collected_articles[article_id]
            content_hash = self._calculate_content_hash(article.content)
            self.content_hashes.discard(content_hash)
            del self.collected_articles[article_id]
        
        logger.info(f"Removed {len(to_remove)} old articles")
        return len(to_remove)


class MockNewsSource:
    """Mock news source for testing."""
    
    def __init__(self) -> None:
        self.sample_news = [
            {
                "title": "贵州茅台发布2026年一季度业绩预告，净利润同比增长15%",
                "content": "贵州茅台酒股份有限公司今日发布2026年第一季度业绩预告，预计实现营业收入350亿元，同比增长12%；净利润180亿元，同比增长15%。公司表示，业绩增长主要得益于产品结构优化和渠道管理加强。",
                "symbols": ["600519.SH"],
            },
            {
                "title": "宁德时代与多家车企签订长期供货协议",
                "content": "宁德时代新能源科技股份有限公司宣布，已与国内外多家知名车企签订长期动力电池供货协议，总金额超过500亿元。这将进一步巩固公司在动力电池领域的领先地位。",
                "symbols": ["300750.SZ"],
            },
            {
                "title": "央行宣布降准0.5个百分点，释放长期资金约1万亿元",
                "content": "中国人民银行今日宣布，决定于2026年5月15日下调金融机构存款准备金率0.5个百分点，此次降准将释放长期资金约1万亿元。此举旨在保持流动性合理充裕，支持实体经济发展。",
                "symbols": [],
            },
        ]
    
    def fetch_latest(self, limit: int = 10) -> list[dict]:
        """Fetch latest news (mock)."""
        return self.sample_news[:limit]


def run_news_collection_pipeline(
    collector: NewsCollector,
    source: Optional[MockNewsSource] = None,
) -> int:
    """
    Run news collection pipeline.
    
    Args:
        collector: News collector
        source: News source (uses mock if None)
        
    Returns:
        Number of articles collected
    """
    if source is None:
        source = MockNewsSource()
    
    articles = source.fetch_latest()
    collected_count = 0
    
    for article_data in articles:
        article = collector.collect_article(
            source="mock_source",
            title=article_data["title"],
            content=article_data["content"],
            symbols=article_data.get("symbols"),
        )
        
        if article:
            collected_count += 1
    
    logger.info(f"Collection complete: {collected_count} new articles")
    return collected_count
