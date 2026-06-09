"""市场数据服务

两层缓存策略：
- 精准缓存（watchlist_cache）：只缓存自选股+持仓，每 3 秒刷新，用新浪单股接口
- 全市场缓存（market_cache）：全量 5000+ 只，每 30 秒刷新，用于涨幅榜/统计
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

log = logging.getLogger("quant.market")

# ---------------------------------------------------------------------------
# 精准缓存 — 自选股 + 持仓，3 秒刷新
# ---------------------------------------------------------------------------
_precise_cache: dict[str, dict] = {}   # symbol(600519.SH) -> quote
_precise_lock = threading.Lock()
_precise_symbols: set[str] = set()     # 需要精准跟踪的 symbols
_precise_thread: Optional[threading.Thread] = None
_PRECISE_TTL = 3  # 秒

# ---------------------------------------------------------------------------
# 全市场缓存 — 30 秒刷新
# ---------------------------------------------------------------------------
_market_cache: dict[str, dict] = {}   # code(6位) -> quote
_market_lock = threading.Lock()
_market_thread: Optional[threading.Thread] = None
_MARKET_TTL = 30  # 秒


def _ak():
    try:
        import akshare as ak
        return ak
    except ImportError:
        raise RuntimeError("请安装 akshare: pip install akshare")


def _to_code(symbol: str) -> str:
    """600519.SH → 600519"""
    return symbol.split(".")[0]


def _is_trading_time() -> bool:
    """判断当前是否为 A 股交易时间（周一至周五 09:15-11:30, 13:00-15:00）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    # 09:15 - 11:30
    m_start = 9 * 60 + 15
    m_end = 11 * 60 + 30
    # 13:00 - 15:00
    a_start = 13 * 60
    a_end = 15 * 60
    return (m_start <= minutes <= m_end) or (a_start <= minutes <= a_end)



def _normalize_code(raw: str) -> str:
    """sh600519 → 600519"""
    raw = str(raw).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if raw.startswith(prefix):
            return raw[2:]
    return raw


def _row_to_quote(row, symbol: str, now: str) -> dict:
    """新浪 spot DataFrame 行 → quote dict"""
    price = float(row.get("最新价") or 0)
    prev_close = float(row.get("昨收") or price)
    change = round(price - prev_close, 2)
    change_pct = round(change / prev_close * 100, 2) if prev_close else 0
    code = symbol.split(".")[0]
    name = str(row.get("名称", ""))
    limit_pct = _limit_pct(code, name)
    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 2),
        "change": change,
        "change_pct": change_pct,
        "volume": int(float(row.get("成交量") or 0)),
        "turnover": float(row.get("成交额") or 0),
        "high": float(row.get("最高") or 0),
        "low": float(row.get("最低") or 0),
        "open": float(row.get("今开") or 0),
        "prev_close": round(prev_close, 2),
        "limit_up": round(prev_close * (1 + limit_pct), 2),
        "limit_down": round(prev_close * (1 - limit_pct), 2),
        "limit_pct": limit_pct,
        "amplitude": 0,
        "turnover_rate": float(row.get("换手率") or 0) if "换手率" in row.index else 0,
        "pe_ratio": 0,
        "pb_ratio": 0,
        "market_cap": 0,
        "timestamp": now,
    }


def _limit_pct(code: str, name: str) -> float:
    """返回当日涨跌停幅度（小数形式）。
    - ST / *ST: 5%
    - 创业板（30）/ 科创板（688）/ 北交所（83/87/88/92）: 20% （北交所 30%）
    - 其他主板: 10%
    """
    if not code:
        return 0.10
    if name and ("ST" in name or "*ST" in name):
        return 0.05
    # 北交所 30%
    if code.startswith(("83", "87", "88", "92")):
        return 0.30
    # 创业板 / 科创板 20%
    if code.startswith(("30", "688")):
        return 0.20
    return 0.10


def _provider_name() -> str:
    try:
        from apps.api.app.core.config import get_settings

        return str(get_settings().market_data_provider or "").strip().lower()
    except Exception:
        return "akshare"


def _is_mock_provider() -> bool:
    return _provider_name() == "mock"


def _mock_stock_map():
    from libs.market_data.universe import UNIVERSE

    return {stock.symbol: stock for stock in UNIVERSE}


def _mock_quote_for_stock(stock) -> dict:
    from libs.market_data.universe import generate_bars

    bars = generate_bars(stock, days=90)
    if not bars:
        return {}
    last = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else last
    trade_date, open_, high, low, close, volume, amount, turnover_rate = last
    prev_close = float(prev[4]) or float(close)
    change = round(float(close) - prev_close, 2)
    change_pct = round(change / prev_close * 100, 2) if prev_close else 0.0
    code = _to_code(stock.symbol)
    limit_pct = _limit_pct(code, stock.name)
    return {
        "symbol": stock.symbol,
        "name": stock.name,
        "price": round(float(close), 2),
        "change": change,
        "change_pct": change_pct,
        "volume": int(volume),
        "turnover": float(amount),
        "high": float(high),
        "low": float(low),
        "open": float(open_),
        "prev_close": round(prev_close, 2),
        "limit_up": round(prev_close * (1 + limit_pct), 2),
        "limit_down": round(prev_close * (1 - limit_pct), 2),
        "limit_pct": limit_pct,
        "amplitude": round((float(high) - float(low)) / prev_close * 100, 2) if prev_close else 0.0,
        "turnover_rate": float(turnover_rate),
        "pe_ratio": 0,
        "pb_ratio": 0,
        "market_cap": 0,
        "timestamp": f"{trade_date.isoformat()}T15:00:00",
    }


def _ensure_mock_market_cache() -> None:
    from libs.market_data.universe import UNIVERSE

    with _market_lock:
        if _market_cache:
            return
        _market_cache.update({
            _to_code(stock.symbol): quote
            for stock in UNIVERSE
            if (quote := _mock_quote_for_stock(stock))
        })


def _mock_kline(symbol: str, period: str = "daily", count: int = 120) -> list[dict]:
    from libs.market_data.universe import generate_bars

    stock = _mock_stock_map().get(symbol)
    if stock is None:
        return []
    bars = generate_bars(stock, days=max(count + 40, 90))
    rows = [
        {
            "date": d.isoformat(),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
            "change_pct": round((close - bars[idx - 1][4]) / bars[idx - 1][4] * 100, 2)
            if idx > 0 and bars[idx - 1][4] else 0,
            "turnover_rate": turnover_rate,
            "is_today": False,
        }
        for idx, (d, open_, high, low, close, volume, amount, turnover_rate) in enumerate(bars)
    ]
    if period == "weekly":
        return rows[-min(count, len(rows))::5] or rows[-min(count, len(rows)):]
    if period == "monthly":
        return rows[-min(count, len(rows))::20] or rows[-min(count, len(rows)):]
    return rows[-min(count, len(rows)):]


# ---------------------------------------------------------------------------
# 精准行情刷新（自选股专用，3秒）
# ---------------------------------------------------------------------------

# 精准跟踪集合上限：超过则按 LRU 丢弃临时注册的 symbol，
# 避免新浪 URL 过长（800 字符以上会被拒绝）
_PRECISE_MAX_SIZE = 80


def register_symbols(symbols: list[str], persistent: bool = True):
    """注册需要精准跟踪的 symbols。

    persistent=True：自选股 + 持仓，永久保留
    persistent=False：临时查询（如扫描器单次拉取），不进入精准集合
    """
    if not persistent:
        return  # 不入精准集合，调用方应自己 _fetch_precise 单次拉取
    with _precise_lock:
        _precise_symbols.update(symbols)
        # 控制大小，避免新浪 URL 过长
        if len(_precise_symbols) > _PRECISE_MAX_SIZE:
            # 简单 LRU：保留 _precise_cache 里有数据的（已被使用过的）
            keep = set(_precise_cache.keys()) & _precise_symbols
            for s in symbols:
                keep.add(s)  # 新加入的优先保留
            if len(keep) > _PRECISE_MAX_SIZE:
                keep = set(list(keep)[:_PRECISE_MAX_SIZE])
            _precise_symbols.clear()
            _precise_symbols.update(keep)


def _fetch_precise(symbols: list[str]) -> dict[str, dict]:
    """用新浪接口批量拉取指定股票的实时行情"""
    if not symbols:
        return {}
    ak = _ak()
    # 新浪接口：传入 sh600519,sz000001 格式
    sina_codes = []
    code_to_symbol = {}
    for sym in symbols:
        code = _to_code(sym)
        exchange = "sh" if code.startswith(("6", "9")) else "sz"
        sina_code = f"{exchange}{code}"
        sina_codes.append(sina_code)
        code_to_symbol[code] = sym

    try:
        # 用新浪实时接口，支持批量
        import httpx
        # 新浪实时行情 API（免费，稳定）
        url = "https://hq.sinajs.cn/list=" + ",".join(sina_codes)
        headers = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        resp = httpx.get(url, headers=headers, timeout=5)
        resp.raise_for_status()

        result = {}
        now = datetime.now().isoformat()
        for line in resp.text.strip().split("\n"):
            if not line or "=" not in line:
                continue
            # var hq_str_sh600519="贵州茅台,1332.73,1342.17,..."
            key_part, val_part = line.split("=", 1)
            sina_code = key_part.strip().replace("var hq_str_", "")
            code = _normalize_code(sina_code)
            symbol = code_to_symbol.get(code)
            if not symbol:
                continue

            val = val_part.strip().strip('"').strip(';')
            if not val or val == "0":
                continue
            fields = val.split(",")
            if len(fields) < 10:
                continue

            try:
                name = fields[0]
                open_ = float(fields[1] or 0)
                prev_close = float(fields[2] or 0)
                price = float(fields[3] or 0)
                high = float(fields[4] or 0)
                low = float(fields[5] or 0)
                volume = int(float(fields[8] or 0))
                turnover = float(fields[9] or 0)
                change = round(price - prev_close, 2)
                change_pct = round(change / prev_close * 100, 2) if prev_close else 0
                limit_pct = _limit_pct(code, name)

                result[symbol] = {
                    "symbol": symbol,
                    "name": name,
                    "price": round(price, 2),
                    "change": change,
                    "change_pct": change_pct,
                    "volume": volume,
                    "turnover": turnover,
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "open": round(open_, 2),
                    "prev_close": round(prev_close, 2),
                    "limit_up": round(prev_close * (1 + limit_pct), 2),
                    "limit_down": round(prev_close * (1 - limit_pct), 2),
                    "limit_pct": limit_pct,
                    "amplitude": round((high - low) / prev_close * 100, 2) if prev_close else 0,
                    "turnover_rate": 0,
                    "pe_ratio": 0,
                    "pb_ratio": 0,
                    "market_cap": 0,
                    "timestamp": now,
                }
            except (ValueError, IndexError):
                continue

        return result
    except Exception as e:
        log.warning("_fetch_precise failed: %s", e)
        return {}


def _precise_refresh_loop():
    """精准行情后台线程：每 3 秒刷新自选股行情"""
    global _precise_cache
    while True:
        try:
            with _precise_lock:
                symbols = list(_precise_symbols)

            if symbols:
                try:
                    data = _fetch_precise(symbols)
                    if data:
                        with _precise_lock:
                            _precise_cache.update(data)
                        log.debug("精准行情刷新: %d 只", len(data))
                except Exception as e:
                    log.warning("精准行情刷新失败: %s", e)

            if _is_trading_time():
                time.sleep(_PRECISE_TTL)
            else:
                time.sleep(60)
        except Exception as e:
            log.exception("精准行情线程意外异常，5秒后重试: %s", e)
            time.sleep(5)


# ---------------------------------------------------------------------------
# 全市场行情刷新（30秒，用于涨幅榜）
# ---------------------------------------------------------------------------

def _fetch_market_all() -> dict[str, dict]:
    """拉取全市场行情（新浪接口）"""
    ak = _ak()
    df = ak.stock_zh_a_spot()
    if df is None or df.empty:
        return {}
    result = {}
    now = datetime.now().isoformat()
    for _, row in df.iterrows():
        raw_code = str(row.get("代码", "")).strip()
        code = _normalize_code(raw_code)
        if not code:
            continue
        price = float(row.get("最新价") or 0)
        prev_close = float(row.get("昨收") or price)
        change = round(price - prev_close, 2)
        change_pct = round(change / prev_close * 100, 2) if prev_close else 0
        exchange = "SH" if code.startswith(("6", "9")) else "SZ"
        name = str(row.get("名称", ""))
        limit_pct = _limit_pct(code, name)
        result[code] = {
            "symbol": f"{code}.{exchange}",
            "name": name,
            "price": round(price, 2),
            "change": change,
            "change_pct": change_pct,
            "volume": int(float(row.get("成交量") or 0)),
            "turnover": float(row.get("成交额") or 0),
            "high": float(row.get("最高") or 0),
            "low": float(row.get("最低") or 0),
            "open": float(row.get("今开") or 0),
            "prev_close": round(prev_close, 2),
            "limit_up": round(prev_close * (1 + limit_pct), 2),
            "limit_down": round(prev_close * (1 - limit_pct), 2),
            "limit_pct": limit_pct,
            "amplitude": 0,
            "turnover_rate": float(row.get("换手率") or 0) if "换手率" in df.columns else 0,
            "pe_ratio": 0,
            "pb_ratio": 0,
            "market_cap": 0,
            "timestamp": now,
        }
    return result


def _market_refresh_loop():
    """全市场行情后台线程：启动立即加载，之后每 30 秒刷新"""
    global _market_cache
    # 启动时立即加载一次
    try:
        log.info("首次加载全市场行情缓存...")
        data = _fetch_market_all()
        if data:
            with _market_lock:
                _market_cache = data
            log.info("全市场缓存首次加载完成，共 %d 只", len(data))
    except Exception as e:
        log.warning("全市场缓存首次加载失败: %s", e)

    while True:
        try:
            if _is_trading_time():
                time.sleep(_MARKET_TTL)
            else:
                time.sleep(60)
            try:
                log.info("刷新全市场行情缓存...")
                data = _fetch_market_all()
                if data:
                    with _market_lock:
                        _market_cache = data
                    log.info("全市场缓存刷新完成，共 %d 只", len(data))
            except Exception as e:
                log.warning("全市场缓存刷新失败: %s", e)
        except Exception as e:
            log.exception("全市场行情线程意外异常，5秒后重试: %s", e)
            time.sleep(5)


def ensure_cache_running():
    """启动两个后台缓存线程"""
    global _precise_thread, _market_thread
    if _is_mock_provider():
        _ensure_mock_market_cache()
        log.info("mock 行情缓存已加载，共 %d 只", len(_market_cache))
        return

    if _precise_thread is None or not _precise_thread.is_alive():
        _precise_thread = threading.Thread(
            target=_precise_refresh_loop, daemon=True, name="precise-quote"
        )
        _precise_thread.start()
        log.info("精准行情线程已启动（3秒刷新）")

    if _market_thread is None or not _market_thread.is_alive():
        _market_thread = threading.Thread(
            target=_market_refresh_loop, daemon=True, name="market-quote"
        )
        _market_thread.start()
        log.info("全市场行情线程已启动（30秒刷新）")


def _cache_ready() -> bool:
    return bool(_market_cache) or bool(_precise_cache)


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def get_realtime_quotes(symbols: list[str]) -> list[dict]:
    """获取批量行情：优先精准缓存，回退全市场缓存"""
    if not symbols:
        return []
    if _is_mock_provider():
        _ensure_mock_market_cache()
        quote_map = {q["symbol"]: q for q in get_all_quotes_snapshot()}
        return [dict(quote_map[symbol]) for symbol in symbols if symbol in quote_map]
    # 确保这些 symbol 被精准跟踪
    register_symbols(symbols)

    result = []
    with _precise_lock:
        precise = dict(_precise_cache)
    with _market_lock:
        market = dict(_market_cache)

    for symbol in symbols:
        # 优先精准缓存
        if symbol in precise:
            result.append(precise[symbol])
            continue
        # 回退全市场缓存
        code = _to_code(symbol)
        if code in market:
            item = dict(market[code])
            item["symbol"] = symbol
            result.append(item)

    return result


def get_single_quote(symbol: str) -> Optional[dict]:
    """获取单股行情。临时查询不会进入精准跟踪集合。"""
    if _is_mock_provider():
        _ensure_mock_market_cache()
        stock = _mock_stock_map().get(symbol)
        return _mock_quote_for_stock(stock) if stock else None

    # 临时查询：不进精准集合，避免大量扫描后 URL 过长
    register_symbols([symbol], persistent=False)

    with _precise_lock:
        q = _precise_cache.get(symbol)
    if q:
        return q

    # 回退全市场缓存
    code = _to_code(symbol)
    with _market_lock:
        q = _market_cache.get(code)
    if q:
        item = dict(q)
        item["symbol"] = symbol
        return item

    # 两个缓存都没有，直接拉一次
    log.info("缓存未命中，直接拉取 %s", symbol)
    data = _fetch_precise([symbol])
    if data and symbol in data:
        with _precise_lock:
            _precise_cache[symbol] = data[symbol]
        return data[symbol]
    return None


def get_hot_stocks(top_n: int = 50) -> list[dict]:
    """涨幅榜（从全市场缓存），top_n 最大 5000"""
    with _market_lock:
        all_q = list(_market_cache.values())
    if not all_q:
        return []
    sorted_q = sorted(all_q, key=lambda x: x.get("change_pct", 0), reverse=True)
    return [
        {
            "symbol": q["symbol"], "name": q["name"],
            "price": q["price"], "change": q.get("change", 0),
            "change_pct": q["change_pct"], "volume": q["volume"],
            "turnover": q.get("turnover", 0),
            "turnover_rate": q.get("turnover_rate", 0),
            "open": q.get("open", 0), "high": q.get("high", 0), "low": q.get("low", 0),
            "prev_close": q.get("prev_close", 0),
        }
        for q in sorted_q[:min(top_n, len(sorted_q))]
    ]


def get_all_quotes_snapshot() -> list[dict]:
    """全市场快照（总览页统计用）"""
    with _market_lock:
        return list(_market_cache.values())


# ---------------------------------------------------------------------------
# K线（腾讯接口）
# ---------------------------------------------------------------------------

def get_kline(symbol: str, period: str = "daily", count: int = 120) -> list[dict]:
    """获取K线，腾讯接口（稳定）+ 今日实时K线"""
    if _is_mock_provider():
        return _mock_kline(symbol, period=period, count=count)

    ak = _ak()
    code = _to_code(symbol)
    exchange = "sh" if code.startswith(("6", "9")) else "sz"
    tx_symbol = f"{exchange}{code}"

    bars = []
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_hist_tx(symbol=tx_symbol, adjust="qfq")
            if df is None or df.empty:
                break

            fetch_count = count * 5 if period != "daily" else count + 20
            df = df.tail(fetch_count)

            if period == "weekly":
                df = _resample_kline(df, "W")
            elif period == "monthly":
                df = _resample_kline(df, "ME")

            prev_close = None
            for _, row in df.tail(count).iterrows():
                close = float(row.get("close") or 0)
                open_ = float(row.get("open") or 0)
                # 腾讯 stock_zh_a_hist_tx 的 amount 实为成交量（手），1 手 = 100 股
                # 单位换算：手 → 股
                tx_amount_lots = float(row.get("amount") or 0)
                volume_shares = int(tx_amount_lots * 100)  # 股数
                # 估算成交额 = 收盘价 × 股数
                turnover_yuan = round(close * volume_shares, 2) if close else 0
                change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close and prev_close > 0 else 0
                prev_close = close
                bars.append({
                    "date": str(row.get("date", "")),
                    "open": round(open_, 2),
                    "high": round(float(row.get("high") or 0), 2),
                    "low": round(float(row.get("low") or 0), 2),
                    "close": round(close, 2),
                    "volume": volume_shares,
                    "amount": turnover_yuan,
                    "change_pct": change_pct,
                    "turnover_rate": 0,
                    "is_today": False,
                })
            break
        except Exception as e:
            log.warning("get_kline attempt %d for %s: %s", attempt + 1, symbol, e)
            if attempt < 2:
                time.sleep(2)

    # 拼接今日实时K线（仅日K）
    if period == "daily":
        today_bar = _get_today_bar(symbol, bars)
        if today_bar:
            today_str = today_bar["date"]
            # 如果最后一根已经是今天，替换；否则追加
            if bars and bars[-1]["date"] == today_str:
                bars[-1] = today_bar
            else:
                bars.append(today_bar)

    return bars


def _get_today_bar(symbol: str, history_bars: list[dict]) -> Optional[dict]:
    """从精准缓存构造今日实时K线"""
    from datetime import date as _date
    today_str = _date.today().strftime("%Y-%m-%d")

    q = get_single_quote(symbol)
    if not q or q.get("price", 0) <= 0:
        return None

    price = q["price"]
    open_ = q.get("open", price)
    high = q.get("high", price)
    low = q.get("low", price)
    prev_close = q.get("prev_close", price)
    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0

    if open_ <= 0:
        open_ = prev_close

    # 用成交量（股数）和历史数据保持一致
    # 新浪接口返回的 volume 是成交量（股），amount/turnover 是成交额（元）
    volume = int(q.get("volume", 0))   # 股数，和腾讯历史数据单位一致

    return {
        "date": today_str,
        "open": round(open_, 2),
        "high": round(max(high, open_, price), 2),
        "low": round(min(low, open_, price) if low > 0 else min(open_, price), 2),
        "close": round(price, 2),
        "volume": volume,
        "amount": float(q.get("turnover", 0)),
        "change_pct": change_pct,
        "turnover_rate": q.get("turnover_rate", 0),
        "is_today": True,
    }


def _resample_kline(df, freq: str):
    try:
        import pandas as pd
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "amount" in df.columns:
            agg["amount"] = "sum"
        if "volume" in df.columns:
            agg["volume"] = "sum"
        resampled = df.resample(freq).agg(agg).dropna().reset_index()
        resampled["date"] = resampled["date"].dt.strftime("%Y-%m-%d")
        return resampled
    except Exception as e:
        log.warning("resample failed: %s", e)
        return df.reset_index() if df.index.name == "date" else df


# ---------------------------------------------------------------------------
# 搜索 & 新闻
# ---------------------------------------------------------------------------

def search_stocks(keyword: str) -> list[dict]:
    if _is_mock_provider():
        raw = keyword.strip().upper()
        result = []
        for stock in _mock_stock_map().values():
            code = _to_code(stock.symbol)
            if raw in code or raw in stock.name.upper() or raw in stock.industry.upper():
                result.append({"symbol": stock.symbol, "name": stock.name, "code": code})
                if len(result) >= 20:
                    break
        return result

    ak = _ak()
    try:
        df = ak.stock_info_a_code_name()
        keyword = keyword.strip().upper()
        result = []
        for _, row in df.iterrows():
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if keyword in code or keyword in name.upper():
                exchange = "SH" if code.startswith(("6", "9")) else "SZ"
                result.append({"symbol": f"{code}.{exchange}", "name": name, "code": code})
                if len(result) >= 20:
                    break
        return result
    except Exception as e:
        log.warning("search_stocks failed: %s", e)
        return []


def get_stock_news(symbol: str, count: int = 10) -> list[dict]:
    if _is_mock_provider():
        stock = _mock_stock_map().get(symbol)
        if not stock:
            return []
        return [
            {
                "title": f"{stock.name} mock 行情样本：趋势 {stock.trend:+.4f}",
                "content": f"{stock.name} 属于{stock.industry}行业；当前为本地 mock 数据，用于无网络演示和自动化测试。",
                "source": "AlphaAgent Mock",
                "time": "2026-04-25 15:00:00",
                "url": "",
            }
            for _ in range(max(0, min(count, 3)))
        ]

    ak = _ak()
    code = _to_code(symbol)
    try:
        df = ak.stock_news_em(symbol=code)
        if df is None or df.empty:
            return []
        news = []
        for _, row in df.head(count).iterrows():
            news.append({
                "title": str(row.get("新闻标题", "")),
                "content": str(row.get("新闻内容", ""))[:500],
                "source": str(row.get("文章来源", "")),
                "time": str(row.get("发布时间", "")),
                "url": str(row.get("新闻链接", "")),
            })
        return news
    except Exception as e:
        log.warning("get_stock_news %s failed: %s", symbol, e)
        return []
