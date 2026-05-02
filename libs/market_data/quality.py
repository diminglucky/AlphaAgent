"""Data quality validation per §5.4.3 of the design doc.

Provides OHLC sanity checks and price-limit boundary checks for A-share bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from libs.quant_core.models import MarketBar


@dataclass
class QualityIssue:
    symbol: str
    trade_date: str
    severity: str  # ERROR | WARN
    code: str
    message: str


@dataclass
class QualityReport:
    total: int = 0
    ok: int = 0
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "ERROR" for i in self.issues)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "ok": self.ok,
            "issues": [
                {
                    "symbol": i.symbol,
                    "trade_date": i.trade_date,
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                }
                for i in self.issues
            ],
            "issue_count": len(self.issues),
        }


def validate_ohlc(bars: Iterable[MarketBar], st: bool = False) -> QualityReport:
    """Check OHLC consistency and price-limit boundaries.

    Rules:
    - high >= max(open, close) and high >= low
    - low <= min(open, close)
    - all positive
    - day-over-day pct_change must be within ±limit (10% normal, 5% ST,
      20% GEM/STAR, 30% Bei) — only ERROR if absurdly out of bounds (>40%)
    - volume / amount non-negative
    """
    report = QualityReport()
    bars_list = list(bars)
    bars_list.sort(key=lambda b: b.trade_date)

    prev_close: Optional[float] = None
    for b in bars_list:
        report.total += 1
        ok = True

        def add(severity: str, code: str, msg: str):
            nonlocal ok
            ok = False
            report.issues.append(QualityIssue(
                symbol=b.symbol,
                trade_date=str(b.trade_date),
                severity=severity, code=code, message=msg,
            ))

        if min(b.open, b.high, b.low, b.close) <= 0:
            add("ERROR", "NON_POSITIVE_PRICE",
                f"OHLC must be positive: open={b.open}, high={b.high}, low={b.low}, close={b.close}")
        if b.high < max(b.open, b.close) or b.high < b.low:
            add("ERROR", "HIGH_INCONSISTENT",
                f"high={b.high} < max(open={b.open}, close={b.close}, low={b.low})")
        if b.low > min(b.open, b.close):
            add("ERROR", "LOW_INCONSISTENT",
                f"low={b.low} > min(open={b.open}, close={b.close})")
        if b.volume < 0 or b.amount < 0:
            add("ERROR", "NEGATIVE_VOLUME", f"volume={b.volume}, amount={b.amount}")

        if prev_close is not None and prev_close > 0:
            pct = (b.close - prev_close) / prev_close
            limit = 0.05 if st else 0.20  # ST 5% / others up to 20%(GEM)
            if abs(pct) > 0.40:
                add("ERROR", "EXTREME_PCT_CHANGE",
                    f"day-over-day change {pct:+.1%} exceeds 40% — likely bad data")
            elif abs(pct) > limit + 0.001:
                add("WARN", "PCT_CHANGE_OVER_LIMIT",
                    f"day-over-day change {pct:+.1%} exceeds normal {limit:.0%} limit")

        if ok:
            report.ok += 1
        prev_close = b.close

    return report
