"""Unit tests for libs/execution/a_share_rules.py."""

from datetime import datetime

from libs.execution.a_share_rules import (
    Board,
    OrderSide,
    RuleViolation,
    calc_limit_prices,
    check_order,
    detect_board,
    is_trading_hours,
    price_limit_pct,
)


# ---------------------------------------------------------------------------
# Board detection
# ---------------------------------------------------------------------------

def test_detect_board_main():
    assert detect_board("600519.SH") == Board.MAIN
    assert detect_board("000001.SZ") == Board.MAIN


def test_detect_board_star():
    assert detect_board("688981.SH") == Board.STAR


def test_detect_board_gem():
    assert detect_board("300750.SZ") == Board.GEM


# ---------------------------------------------------------------------------
# Price limits
# ---------------------------------------------------------------------------

def test_price_limit_main_normal():
    assert price_limit_pct(Board.MAIN, is_st=False) == 0.10


def test_price_limit_main_st():
    assert price_limit_pct(Board.MAIN, is_st=True) == 0.05


def test_price_limit_star_gem():
    assert price_limit_pct(Board.STAR, is_st=False) == 0.20
    assert price_limit_pct(Board.GEM, is_st=False) == 0.20


def test_calc_limit_prices_main():
    low, high = calc_limit_prices(100.0, Board.MAIN, is_st=False)
    assert low == 90.0
    assert high == 110.0


def test_calc_limit_prices_st():
    low, high = calc_limit_prices(10.0, Board.MAIN, is_st=True)
    assert low == 9.5
    assert high == 10.5


# ---------------------------------------------------------------------------
# Order rule checks
# ---------------------------------------------------------------------------

def test_buy_passes_normal_case():
    r = check_order(
        symbol="600519.SH", side=OrderSide.BUY,
        quantity=100, price=1700.0, prev_close=1700.0,
    )
    assert r.ok
    assert r.violations == []


def test_buy_lot_size_violation():
    r = check_order(
        symbol="600519.SH", side=OrderSide.BUY,
        quantity=150, price=1700.0, prev_close=1700.0,
    )
    assert not r.ok
    assert RuleViolation.LOT_SIZE in r.violations


def test_sell_odd_lot_allowed():
    r = check_order(
        symbol="600519.SH", side=OrderSide.SELL,
        quantity=50, price=1700.0, prev_close=1700.0,
        available_quantity=100,
    )
    assert r.ok


def test_sell_t1_blocked():
    r = check_order(
        symbol="600519.SH", side=OrderSide.SELL,
        quantity=200, price=1700.0, prev_close=1700.0,
        available_quantity=100,
    )
    assert not r.ok
    assert RuleViolation.INSUFFICIENT_AVAIL in r.violations


def test_buy_above_limit_up_blocked():
    # Main board ±10 %: limit-up of 100 is 110
    r = check_order(
        symbol="600519.SH", side=OrderSide.BUY,
        quantity=100, price=111.0, prev_close=100.0,
    )
    assert not r.ok
    assert RuleViolation.PRICE_LIMIT_UP in r.violations


def test_buy_below_limit_down_blocked():
    r = check_order(
        symbol="600519.SH", side=OrderSide.BUY,
        quantity=100, price=89.0, prev_close=100.0,
    )
    assert not r.ok
    assert RuleViolation.PRICE_LIMIT_DOWN in r.violations


def test_st_block_when_enabled():
    r = check_order(
        symbol="600100.SH", side=OrderSide.BUY,
        quantity=100, price=10.0, prev_close=10.0,
        is_st=True, block_st=True,
    )
    assert not r.ok
    assert RuleViolation.ST_STOCK_BLOCKED in r.violations


def test_st_5pct_limit():
    # ST stock: 100 * 1.05 = 105 should pass; 105.5 should fail
    r = check_order(
        symbol="600100.SH", side=OrderSide.BUY,
        quantity=100, price=105.0, prev_close=100.0, is_st=True,
    )
    assert r.ok

    r = check_order(
        symbol="600100.SH", side=OrderSide.BUY,
        quantity=100, price=105.5, prev_close=100.0, is_st=True,
    )
    assert not r.ok
    assert RuleViolation.PRICE_LIMIT_UP in r.violations


def test_star_20pct_limit():
    r = check_order(
        symbol="688981.SH", side=OrderSide.BUY,
        quantity=100, price=119.0, prev_close=100.0,
    )
    assert r.ok

    r = check_order(
        symbol="688981.SH", side=OrderSide.BUY,
        quantity=100, price=125.0, prev_close=100.0,
    )
    assert not r.ok


def test_delisted_blocked():
    r = check_order(
        symbol="600100.SH", side=OrderSide.BUY,
        quantity=100, price=10.0, prev_close=10.0,
        is_delisted=True,
    )
    assert not r.ok
    assert RuleViolation.DELISTED in r.violations


def test_invalid_quantity():
    r = check_order(
        symbol="600519.SH", side=OrderSide.BUY,
        quantity=0, price=10.0, prev_close=10.0,
    )
    assert not r.ok
    assert RuleViolation.INVALID_QUANTITY in r.violations


# ---------------------------------------------------------------------------
# Trading hours
# ---------------------------------------------------------------------------

def test_is_trading_hours_morning():
    assert is_trading_hours(datetime(2026, 4, 27, 10, 0))


def test_is_trading_hours_lunch_break():
    assert not is_trading_hours(datetime(2026, 4, 27, 12, 0))


def test_is_trading_hours_weekend():
    # Saturday
    assert not is_trading_hours(datetime(2026, 4, 25, 10, 0))


def test_trading_hours_block():
    r = check_order(
        symbol="600519.SH", side=OrderSide.BUY,
        quantity=100, price=1700.0, prev_close=1700.0,
        enforce_trading_hours=True,
        now=datetime(2026, 4, 25, 10, 0),  # Saturday
    )
    assert not r.ok
    assert RuleViolation.OUTSIDE_TRADING_HOURS in r.violations
