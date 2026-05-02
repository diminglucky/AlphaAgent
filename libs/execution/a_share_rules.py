"""A-share specific trading rule checks.

Based on real-world rules enforced by Chinese exchanges (Shanghai, Shenzhen)
and broker terminals like MiniQMT (referenced from OSkhQuant project):

1. T+1 settlement — same-day buys cannot be sold the same day.
2. Price limits — daily ±10% (普通股), ±5% (ST股), ±20% (创业板/科创板).
3. Lot size — buy orders must be in multiples of 100 shares (一手).
4. Sell can be any quantity ≥ 1 (allowed to sell odd lots) but only the
   "available_quantity" can be sold (T+1 lock).
5. Trading hours — 09:30-11:30, 13:00-15:00 on weekdays (excluding holidays).
6. Reject ST stocks for new buys when configured.

These checks are intentionally pure functions so they can be unit-tested
without any database or broker connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Board(str, Enum):
    """Mainboard / GEM (创业板) / STAR (科创板) — different price limits."""
    MAIN = "MAIN"           # 主板 ±10 %
    STAR = "STAR"           # 科创板 688xxx ±20 %
    GEM = "GEM"             # 创业板 30xxxx ±20 %
    BJSE = "BJSE"           # 北交所 ±30 %


class RuleViolation(str, Enum):
    LOT_SIZE = "LOT_SIZE"               # 100-share multiple violation
    INSUFFICIENT_AVAIL = "INSUFFICIENT_AVAIL"  # T+1 not yet settled
    PRICE_LIMIT_UP = "PRICE_LIMIT_UP"
    PRICE_LIMIT_DOWN = "PRICE_LIMIT_DOWN"
    OUTSIDE_TRADING_HOURS = "OUTSIDE_TRADING_HOURS"
    ST_STOCK_BLOCKED = "ST_STOCK_BLOCKED"
    DELISTED = "DELISTED"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_PRICE = "INVALID_PRICE"


@dataclass(frozen=True)
class RuleResult:
    ok: bool
    violations: list[RuleViolation]
    messages: list[str]

    @property
    def message(self) -> str:
        return "; ".join(self.messages)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def detect_board(symbol: str) -> Board:
    """Infer board from the symbol's prefix."""
    code = symbol.split(".")[0]
    if code.startswith("688"):
        return Board.STAR
    if code.startswith("30"):
        return Board.GEM
    if symbol.endswith(".BJ") or code.startswith(("43", "83", "87", "88")):
        return Board.BJSE
    return Board.MAIN


def price_limit_pct(board: Board, is_st: bool) -> float:
    """Return the daily price-change limit as a fraction (e.g., 0.10)."""
    if is_st:
        # ST shares on the main board: ±5 %
        # ST shares on STAR/GEM are still subject to STAR/GEM limits
        if board == Board.MAIN:
            return 0.05
    if board in (Board.STAR, Board.GEM):
        return 0.20
    if board == Board.BJSE:
        return 0.30
    return 0.10


def calc_limit_prices(prev_close: float, board: Board, is_st: bool) -> tuple[float, float]:
    """Return (limit_down, limit_up) prices, rounded to 2 decimals."""
    pct = price_limit_pct(board, is_st)
    return round(prev_close * (1 - pct), 2), round(prev_close * (1 + pct), 2)


# ---------------------------------------------------------------------------
# Trading hours
# ---------------------------------------------------------------------------

MORNING_START = time(9, 30)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)


def is_trading_hours(now: Optional[datetime] = None) -> bool:
    """Coarse check: weekday + 09:30-11:30 / 13:00-15:00.
    Note: real implementation should also check the trading calendar."""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (MORNING_START <= t <= MORNING_END) or (AFTERNOON_START <= t <= AFTERNOON_END)


# ---------------------------------------------------------------------------
# Main rule check
# ---------------------------------------------------------------------------

def check_order(
    *,
    symbol: str,
    side: OrderSide,
    quantity: int,
    price: float,
    prev_close: float,
    available_quantity: int = 0,        # only relevant for SELL
    is_st: bool = False,
    is_delisted: bool = False,
    block_st: bool = False,
    enforce_trading_hours: bool = False,  # default off for backtests/sims
    now: Optional[datetime] = None,
) -> RuleResult:
    """
    Check an order against A-share rules.

    Args:
        symbol: e.g. "600519.SH"
        side: BUY / SELL
        quantity: number of shares
        price: limit price (¥). For market orders pass last_price.
        prev_close: yesterday's close (used for limit-up/down calculation)
        available_quantity: shares free to sell (T+1 lock honored for SELL)
        is_st: whether the stock is ST (subject to ±5 % limit on main board)
        is_delisted: hard block any order
        block_st: when True, BUY orders for ST stocks are rejected
        enforce_trading_hours: enable trading-hours check
        now: datetime to use for trading-hours check (testing)

    Returns:
        RuleResult with `ok=True` if order passes all checks.
    """
    violations: list[RuleViolation] = []
    messages: list[str] = []

    # 0) Basic sanity
    if quantity <= 0:
        violations.append(RuleViolation.INVALID_QUANTITY)
        messages.append("数量必须大于 0")
    if price <= 0:
        violations.append(RuleViolation.INVALID_PRICE)
        messages.append("价格必须大于 0")

    # 1) Delisted
    if is_delisted:
        violations.append(RuleViolation.DELISTED)
        messages.append("该股票已退市，无法交易")

    # 2) ST block (BUY only, when configured)
    if side == OrderSide.BUY and is_st and block_st:
        violations.append(RuleViolation.ST_STOCK_BLOCKED)
        messages.append("已开启 ST 股票拦截，禁止买入 ST 股票")

    # 3) Lot size — BUY must be 100-multiple. SELL can be odd lots
    if side == OrderSide.BUY and quantity % 100 != 0:
        violations.append(RuleViolation.LOT_SIZE)
        messages.append(f"买入数量必须是 100 股的整数倍（当前 {quantity}）")

    # 4) T+1 — SELL cannot exceed available_quantity
    if side == OrderSide.SELL and quantity > available_quantity:
        violations.append(RuleViolation.INSUFFICIENT_AVAIL)
        messages.append(
            f"可卖数量不足（持有可用 {available_quantity} 股，欲卖 {quantity} 股）"
            f"，可能触发 T+1 限制"
        )

    # 5) Price limit
    if prev_close > 0:
        board = detect_board(symbol)
        low, high = calc_limit_prices(prev_close, board, is_st)
        if price > high + 1e-6:
            violations.append(RuleViolation.PRICE_LIMIT_UP)
            messages.append(f"申报价 ¥{price:.2f} 高于涨停价 ¥{high:.2f}")
        if price < low - 1e-6:
            violations.append(RuleViolation.PRICE_LIMIT_DOWN)
            messages.append(f"申报价 ¥{price:.2f} 低于跌停价 ¥{low:.2f}")

    # 6) Trading hours
    if enforce_trading_hours and not is_trading_hours(now):
        violations.append(RuleViolation.OUTSIDE_TRADING_HOURS)
        messages.append("非交易时段（09:30-11:30 / 13:00-15:00）")

    return RuleResult(ok=not violations, violations=violations, messages=messages)
