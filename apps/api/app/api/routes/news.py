"""News article and event endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.app.core.auth import AuthenticatedUser, get_current_user, require_trader
from apps.api.app.db.session import get_db
from apps.api.app.schemas.news import (
    AddNewsEventRequest,
    IngestArticleRequest,
    NewsArticleResponse,
    NewsEventResponse,
)
from apps.api.app.services.news_service import NewsService

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/articles", response_model=list[NewsArticleResponse])
def list_articles(
    symbol: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[NewsArticleResponse]:
    articles = NewsService(db).list_articles(symbol=symbol, limit=limit)
    return [
        NewsArticleResponse(
            article_id=a.article_id,
            source=a.source,
            title=a.title,
            published_at=a.published_at,
            url=a.url,
            symbols=a.symbols,
            created_at=a.created_at,
        )
        for a in articles
    ]


@router.post("/articles", response_model=NewsArticleResponse, status_code=201)
def ingest_article(
    req: IngestArticleRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
) -> NewsArticleResponse:
    try:
        article = NewsService(db).ingest_article(
            source=req.source,
            title=req.title,
            raw_text=req.raw_text,
            published_at=req.published_at,
            symbols=req.symbols,
            url=req.url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NewsArticleResponse(
        article_id=article.article_id,
        source=article.source,
        title=article.title,
        published_at=article.published_at,
        url=article.url,
        symbols=article.symbols,
        created_at=article.created_at,
    )


@router.post("/articles/{article_id}/events", response_model=NewsEventResponse, status_code=201)
def add_event(
    article_id: str,
    req: AddNewsEventRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_trader),
) -> NewsEventResponse:
    event = NewsService(db).add_event(
        article_id=article_id,
        event_type=req.event_type,
        sentiment_score=req.sentiment_score,
        urgency_score=req.urgency_score,
        relevance_score=req.relevance_score,
        summary=req.summary,
        llm_reasoning_version=req.llm_reasoning_version,
    )
    return NewsEventResponse(
        event_id=event.event_id,
        article_id=event.article_id,
        event_type=event.event_type,
        sentiment_score=event.sentiment_score,
        urgency_score=event.urgency_score,
        relevance_score=event.relevance_score,
        summary=event.summary,
        llm_reasoning_version=event.llm_reasoning_version,
        created_at=event.created_at,
    )


@router.get("/symbols/{symbol}/events", response_model=list[NewsEventResponse])
def list_events_for_symbol(
    symbol: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[NewsEventResponse]:
    events = NewsService(db).list_events_for_symbol(symbol=symbol, limit=limit)
    return [
        NewsEventResponse(
            event_id=e.event_id,
            article_id=e.article_id,
            event_type=e.event_type,
            sentiment_score=e.sentiment_score,
            urgency_score=e.urgency_score,
            relevance_score=e.relevance_score,
            summary=e.summary,
            llm_reasoning_version=e.llm_reasoning_version,
            created_at=e.created_at,
        )
        for e in events
    ]
