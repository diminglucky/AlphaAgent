from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NewsArticleResponse(BaseModel):
    article_id: str
    source: str
    title: str
    published_at: datetime
    url: Optional[str]
    symbols: list[str]
    created_at: datetime


class NewsEventResponse(BaseModel):
    event_id: str
    article_id: str
    event_type: str
    sentiment_score: float
    urgency_score: float
    relevance_score: float
    summary: str
    llm_reasoning_version: str
    created_at: datetime


class IngestArticleRequest(BaseModel):
    source: str
    title: str
    raw_text: str
    published_at: datetime
    symbols: list[str] = Field(default_factory=list)
    url: Optional[str] = None


class AddNewsEventRequest(BaseModel):
    event_type: str
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    urgency_score: float = Field(..., ge=0.0, le=1.0)
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    summary: str
    llm_reasoning_version: str = "keyword_v1"
