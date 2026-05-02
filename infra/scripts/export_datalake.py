#!/usr/bin/env python3
"""Export DB time-series into the parquet research data lake.

Usage:
    python infra/scripts/export_datalake.py            # all watchlisted symbols
    python infra/scripts/export_datalake.py 600519.SH 000001.SZ
    python infra/scripts/export_datalake.py --factors  # dump factor_snapshots

Requires pandas + pyarrow. Pass --check to verify install only.
"""

from __future__ import annotations

import argparse
import json
import sys

from apps.api.app.db.session import session_scope
from apps.api.app.services.market_service import MarketService
from apps.api.app.services.watchlist_service import WatchlistService
from libs.research.datalake import ParquetDataLake, is_available, is_duckdb_available


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("symbols", nargs="*", help="Symbols to export. Empty = all watchlisted.")
    p.add_argument("--factors", action="store_true", help="Also export factor_snapshots.")
    p.add_argument("--check", action="store_true", help="Only print availability.")
    args = p.parse_args()

    print(json.dumps({
        "pandas+pyarrow": is_available(),
        "duckdb": is_duckdb_available(),
    }, indent=2))
    if args.check:
        return 0 if is_available() else 2
    if not is_available():
        print("ERROR: pandas + pyarrow required. pip install pandas pyarrow", file=sys.stderr)
        return 2

    lake = ParquetDataLake()

    if args.symbols:
        symbols = list(args.symbols)
    else:
        with session_scope() as s:
            symbols = WatchlistService(s).list_symbols("default")
        if not symbols:
            print("No symbols (watchlist empty). Pass symbols on the command line.")
            return 1

    market = MarketService()
    summary = lake.export_daily_bars(market, symbols)
    print(json.dumps({"bars_export": summary}, default=str, indent=2))

    if args.factors:
        with session_scope() as s:
            n = lake.export_factor_snapshots(s)
        print(json.dumps({"factor_snapshots_exported": n}, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
