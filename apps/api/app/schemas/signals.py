from datetime import datetime

from pydantic import BaseModel, Field


class SignalSnapshotResponse(BaseModel):
    signal_id: str
    symbol: str
    as_of_time: datetime
    signal_type: str
    raw_score: float
    confidence: float
    components: dict
    expected_horizon: str
    model_version: str


class SaveSignalRequest(BaseModel):
    symbol: str
    signal_type: str = Field(..., examples=["TECHNICAL", "MOMENTUM"])
    raw_score: float = Field(..., ge=-1.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    components: dict = Field(default_factory=dict)
    expected_horizon: str = Field(default="swing_5d")
