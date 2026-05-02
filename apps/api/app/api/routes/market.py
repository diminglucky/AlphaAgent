from dataclasses import asdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from apps.api.app.schemas.market import (
    InstrumentResponse,
    MarketBarResponse,
    RealtimeQuoteResponse,
)
from apps.api.app.schemas.provider import ProviderStatusResponse
from apps.api.app.services.market_service import MarketService


router = APIRouter(prefix="/market", tags=["market"])
service = MarketService()


@router.get("/provider/status", response_model=ProviderStatusResponse)
def get_provider_status() -> ProviderStatusResponse:
    return ProviderStatusResponse(**service.get_provider_status().__dict__)


@router.get("/instruments", response_model=list[InstrumentResponse])
def list_instruments() -> list[InstrumentResponse]:
    return [InstrumentResponse(**asdict(item)) for item in service.list_instruments()]


@router.get("/bars", response_model=list[MarketBarResponse])
def list_bars(
    symbol: str = Query(..., description="Ticker with exchange suffix, e.g. 600519.SH"),
    freq: str = Query("1d", description="Supported frequencies: 1d, 1m"),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
) -> list[MarketBarResponse]:
    try:
        bars = service.get_bars(symbol=symbol, freq=freq, start=start, end=end)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return [MarketBarResponse(**asdict(item)) for item in bars]


@router.get("/quotes/realtime", response_model=list[RealtimeQuoteResponse])
def get_realtime_quotes(symbols: str = Query(...)) -> list[RealtimeQuoteResponse]:
    symbol_list = [item.strip() for item in symbols.split(",") if item.strip()]

    if not symbol_list:
        raise HTTPException(status_code=400, detail="At least one symbol is required.")

    quotes = service.get_realtime_quotes(symbol_list)
    return [RealtimeQuoteResponse(**asdict(item)) for item in quotes]
