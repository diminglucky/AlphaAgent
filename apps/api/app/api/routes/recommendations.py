from dataclasses import asdict

from fastapi import APIRouter

from apps.api.app.schemas.recommendation import (
    RecommendationExplainRequest,
    RecommendationExplainResponse,
    RecommendationItemResponse,
    RecommendationListResponse,
)
from apps.api.app.services.recommendation_service import RecommendationService


router = APIRouter(prefix="/recommendations", tags=["recommendations"])
service = RecommendationService()


@router.get("/latest", response_model=RecommendationListResponse)
def latest_recommendations() -> RecommendationListResponse:
    payload = service.get_latest_recommendations()
    return RecommendationListResponse(
        as_of=payload["as_of"],
        items=[RecommendationItemResponse(**asdict(item)) for item in payload["items"]],
    )


@router.post("/explain", response_model=RecommendationExplainResponse)
def explain_recommendation(
    request: RecommendationExplainRequest,
) -> RecommendationExplainResponse:
    explanation = service.explain_recommendation(request.symbol)
    return RecommendationExplainResponse(**explanation)

