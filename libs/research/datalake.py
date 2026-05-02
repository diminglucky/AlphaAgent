"""Parquet / DuckDB research data warehouse (Design Doc §5.3.4 / §10.6).

Lightweight, dependency-light persistence of time-series for offline analysis:

- Daily bars are exported to parquet partitioned by symbol:
        data/datalake/bars_1d/symbol=600519.SH/part.parquet
- DuckDB can query the lake directly with `read_parquet('data/datalake/...')`.
- All writes are idempotent (overwrites the symbol partition).
- Optional dependency: pandas + pyarrow + duckdb. If absent, an explicit
  `RuntimeError` is raised — callers should guard with `is_available()`.

Typical use (CLI / scheduler):
        from libs.research.datalake import ParquetDataLake
        lake = ParquetDataLake()
        lake.export_daily_bars(market_service, symbols=["600519.SH"])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("quant.datalake")


def is_available() -> bool:
    """Whether the optional pandas + pyarrow stack is importable."""
    try:
        import pandas  # noqa: F401
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


def is_duckdb_available() -> bool:
    try:
        import duckdb  # noqa: F401
        return True
    except ImportError:
        return False


class ParquetDataLake:
    """Symbol-partitioned parquet lake for daily bars and factors."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or "data/datalake")
        self.root.mkdir(parents=True, exist_ok=True)

    # --- daily bars ----------------------------------------------------

    def bars_path(self, symbol: str) -> Path:
        return self.root / "bars_1d" / f"symbol={symbol}" / "part.parquet"

    def export_daily_bars(
        self,
        market_service,
        symbols: Iterable[str],
    ) -> dict:
        """Pull bars from a MarketService and write per-symbol parquet files.

        Returns a summary dict {symbol: nrows_or_error}.
        """
        if not is_available():
            raise RuntimeError(
                "pandas + pyarrow not installed. Install with: pip install pandas pyarrow"
            )
        import pandas as pd  # type: ignore

        result: dict[str, object] = {}
        for sym in symbols:
            try:
                bars = market_service.get_bars(symbol=sym, freq="1d")
                if not bars:
                    result[sym] = 0
                    continue
                df = pd.DataFrame([{
                    "symbol": b.symbol,
                    "trade_date": b.trade_date,
                    "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                    "volume": b.volume, "amount": b.amount,
                    "turnover_rate": b.turnover_rate,
                    "adj_type": b.adj_type, "data_source": b.data_source,
                } for b in bars])
                p = self.bars_path(sym)
                p.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(p, index=False)
                result[sym] = len(df)
            except Exception as exc:  # noqa: BLE001
                log.warning("export %s failed: %s", sym, exc)
                result[sym] = f"error: {exc}"
        return result

    # --- factor snapshots ---------------------------------------------

    def factors_path(self) -> Path:
        return self.root / "factor_snapshots.parquet"

    def export_factor_snapshots(self, db_session) -> int:
        """Dump entire factor_snapshots table to a single parquet file."""
        if not is_available():
            raise RuntimeError("pandas + pyarrow not installed")
        import pandas as pd  # type: ignore

        from apps.api.app.db.models import FactorSnapshotORM
        rows = db_session.query(FactorSnapshotORM).all()
        if not rows:
            return 0
        df = pd.DataFrame([{
            "symbol": r.symbol, "as_of_time": r.as_of_time,
            "factor_name": r.factor_name, "factor_value": r.factor_value,
            "feature_set_version": r.feature_set_version,
            "data_source": r.data_source,
        } for r in rows])
        p = self.factors_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)
        return len(df)

    # --- DuckDB query helper ------------------------------------------

    def query(self, sql: str) -> list[dict]:
        """Run a DuckDB query against the lake.

        The lake root is registered as a DuckDB view named `lake`.
        Use `read_parquet('${lake}/bars_1d/symbol=*/part.parquet')` etc.
        """
        if not is_duckdb_available():
            raise RuntimeError("duckdb not installed. Install with: pip install duckdb")
        import duckdb  # type: ignore

        conn = duckdb.connect(":memory:")
        # Register the lake root path for ergonomic substitution
        sql_resolved = sql.replace("${lake}", str(self.root))
        rows = conn.execute(sql_resolved).fetchall()
        cols = [d[0] for d in conn.description] if conn.description else []
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
