"""News ingestion and retrieval service."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from apps.api.app.db.repositories import NewsRepository
from libs.llm_analyst.analyzer import NewsAnalyzer, NewsArticle as _AnalyzerArticle
from libs.quant_core.models import NewsArticleRecord, NewsEventRecord


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class NewsService:
    def __init__(self, session: Session) -> None:
        self._repo = NewsRepository(session)
        # Analyzer is cheap to construct (keyword fallback by default)
        self._analyzer = NewsAnalyzer(use_llm=False)

    def ingest_article(
        self,
        source: str,
        title: str,
        raw_text: str,
        published_at: datetime,
        symbols: list[str],
        url: Optional[str] = None,
        auto_analyze: bool = True,
    ) -> NewsArticleRecord:
        content_hash = _hash(raw_text)
        if self._repo.article_exists(content_hash):
            raise ValueError("Duplicate article (same content hash)")

        article = NewsArticleRecord(
            article_id=str(uuid.uuid4()),
            source=source,
            title=title,
            published_at=published_at,
            url=url,
            content_hash=content_hash,
            raw_text=raw_text,
            symbols=symbols,
            created_at=_now(),
        )
        self._repo.save_article(article)

        # Auto-derive a NewsEvent so downstream consumers (advisor, dashboard)
        # see sentiment + urgency immediately without a separate API call.
        if auto_analyze:
            try:
                analysis = self._analyzer.analyze(_AnalyzerArticle(
                    article_id=article.article_id,
                    source=source,
                    title=title,
                    content=raw_text,
                    published_at=published_at,
                    url=url,
                    symbols=symbols,
                ))
                self.add_event(
                    article_id=article.article_id,
                    event_type=analysis.event_type.value,
                    sentiment_score=analysis.sentiment_score,
                    urgency_score=analysis.urgency_score,
                    relevance_score=analysis.relevance_score,
                    summary=analysis.summary or title,
                    llm_reasoning_version="keyword_v1",
                )
            except Exception:  # noqa: BLE001
                # Best-effort — don't fail ingestion if analysis errors
                pass

        return article

    def add_event(
        self,
        article_id: str,
        event_type: str,
        sentiment_score: float,
        urgency_score: float,
        relevance_score: float,
        summary: str,
        llm_reasoning_version: str = "keyword_v1",
    ) -> NewsEventRecord:
        event = NewsEventRecord(
            event_id=str(uuid.uuid4()),
            article_id=article_id,
            event_type=event_type,
            sentiment_score=sentiment_score,
            urgency_score=urgency_score,
            relevance_score=relevance_score,
            summary=summary,
            llm_reasoning_version=llm_reasoning_version,
            created_at=_now(),
        )
        self._repo.save_event(event)
        return event

    def list_articles(self, symbol: Optional[str] = None, limit: int = 20) -> list[NewsArticleRecord]:
        return self._repo.list_articles(symbol=symbol, limit=limit)

    def list_events_for_symbol(self, symbol: str, limit: int = 20) -> list[NewsEventRecord]:
        return self._repo.list_events_for_symbol(symbol=symbol, limit=limit)
