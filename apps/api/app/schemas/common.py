from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    app_name: str
    environment: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str | None = None
