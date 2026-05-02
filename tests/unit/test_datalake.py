"""Test parquet datalake export round-trip."""

from __future__ import annotations

from datetime import date

import pytest

from libs.quant_core.models import MarketBar
from libs.research.datalake import ParquetDataLake, is_available


pytestmark = pytest.mark.skipif(not is_available(), reason="pandas/pyarrow not installed")


class _StubMarket:
    def get_bars(self, symbol: str, freq: str = "1d") -> list[MarketBar]:
        return [
            MarketBar(
                symbol=symbol, trade_date=date(2026, 4, 28),
                open=100.0, high=101.0, low=99.0, close=100.5,
                volume=1_000_000, amount=1.005e8,
                turnover_rate=0.01, adj_type="qfq", data_source="stub",
            ),
            MarketBar(
                symbol=symbol, trade_date=date(2026, 4, 29),
                open=100.5, high=102.0, low=100.0, close=101.5,
                volume=1_200_000, amount=1.218e8,
                turnover_rate=0.012, adj_type="qfq", data_source="stub",
            ),
        ]


def test_export_round_trip(tmp_path):
    lake = ParquetDataLake(root=tmp_path)
    summary = lake.export_daily_bars(_StubMarket(), symbols=["600519.SH"])
    assert summary["600519.SH"] == 2

    p = lake.bars_path("600519.SH")
    assert p.exists()
    import pandas as pd
    df = pd.read_parquet(p)
    assert len(df) == 2
    assert set(df.columns) >= {"symbol", "trade_date", "close"}
    assert df.iloc[0]["symbol"] == "600519.SH"
