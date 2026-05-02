"""A-share universe — 30+ liquid stocks with deterministic synthetic bars.

When AKShare is configured this file isn't used. In mock mode this provides
enough breadth (multiple trending profiles) so that the market scanner can
actually rank stocks instead of seeing only 3 symbols.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass(frozen=True)
class UniverseStock:
    symbol: str
    name: str
    industry: str
    base_price: float
    # trend: positive = up-trending, negative = down-trending, near 0 = range
    trend: float
    # vol: daily noise level
    vol: float
    is_st: bool = False


# 30 liquid A-share names with varied profiles
UNIVERSE: list[UniverseStock] = [
    # 白酒
    UniverseStock("600519.SH", "贵州茅台", "白酒",        1700.0,  +0.0030, 0.012),
    UniverseStock("000858.SZ", "五粮液",   "白酒",         145.0,  +0.0020, 0.014),
    UniverseStock("000568.SZ", "泸州老窖", "白酒",         165.0,  -0.0010, 0.018),
    # 银行
    UniverseStock("000001.SZ", "平安银行", "银行",          11.4,  +0.0008, 0.010),
    UniverseStock("600036.SH", "招商银行", "银行",          38.5,  +0.0015, 0.011),
    UniverseStock("601398.SH", "工商银行", "银行",           5.6,  +0.0005, 0.008),
    UniverseStock("601318.SH", "中国平安", "保险",          48.0,  -0.0020, 0.016),
    # 新能源/电池
    UniverseStock("300750.SZ", "宁德时代", "电池",         245.0,  +0.0040, 0.022),
    UniverseStock("002594.SZ", "比亚迪",   "新能源车",     265.0,  +0.0035, 0.024),
    UniverseStock("600905.SH", "三峡能源", "电力",           4.5,  +0.0018, 0.014),
    # 互联网/科技
    UniverseStock("002415.SZ", "海康威视", "电子",          31.0,  +0.0010, 0.018),
    UniverseStock("002230.SZ", "科大讯飞", "AI",            55.0,  +0.0050, 0.030),
    UniverseStock("000063.SZ", "中兴通讯", "通信",          28.0,  +0.0012, 0.020),
    UniverseStock("002475.SZ", "立讯精密", "电子",          38.0,  -0.0008, 0.022),
    # 半导体
    UniverseStock("688981.SH", "中芯国际", "半导体",        62.0,  +0.0025, 0.028),
    UniverseStock("002371.SZ", "北方华创", "半导体设备",   320.0,  +0.0030, 0.026),
    # 医药
    UniverseStock("600276.SH", "恒瑞医药", "医药",          45.0,  -0.0015, 0.018),
    UniverseStock("300760.SZ", "迈瑞医疗", "医疗器械",     280.0,  +0.0008, 0.020),
    UniverseStock("603259.SH", "药明康德", "CXO",           65.0,  -0.0030, 0.024),
    # 消费
    UniverseStock("600887.SH", "伊利股份", "乳业",          28.0,  -0.0005, 0.013),
    UniverseStock("000333.SZ", "美的集团", "家电",          70.0,  +0.0020, 0.015),
    UniverseStock("000651.SZ", "格力电器", "家电",          40.0,  +0.0010, 0.014),
    # 资源/有色
    UniverseStock("601899.SH", "紫金矿业", "有色",          15.0,  +0.0040, 0.020),
    UniverseStock("600547.SH", "山东黄金", "黄金",          22.0,  +0.0030, 0.022),
    # 地产
    UniverseStock("000002.SZ", "万科A",   "地产",            8.5,  -0.0040, 0.020),
    # 军工
    UniverseStock("000768.SZ", "中航西飞", "军工",          32.0,  +0.0015, 0.024),
    # 周期
    UniverseStock("601857.SH", "中国石油", "石油",           7.8,  +0.0008, 0.012),
    UniverseStock("600028.SH", "中国石化", "石油",           6.5,  +0.0006, 0.011),
    # 农业
    UniverseStock("000876.SZ", "新希望",   "农业",          12.0,  -0.0020, 0.022),
    # ST 例子
    UniverseStock("600179.SH", "*ST安通",  "物流",           3.2,  -0.0050, 0.030, is_st=True),
]


def generate_bars(stock: UniverseStock, days: int = 60, end: Optional[date] = None) -> list[tuple]:
    """Deterministic synthetic OHLC bars (60 days back from `end`).

    Returns a list of (date, open, high, low, close, volume, amount, turnover_rate).
    """
    end = end or date(2026, 4, 25)
    # Seed by symbol so trajectory is stable across runs
    seed = sum(ord(c) for c in stock.symbol)
    bars: list[tuple] = []
    price = stock.base_price * (1 - stock.trend * days / 2)  # start point
    for i in range(days):
        d = end - timedelta(days=days - i - 1)
        # Skip weekends
        if d.weekday() >= 5:
            continue
        # Deterministic "noise" via sine waves with different phases
        noise = (
            math.sin((seed + i) * 0.7) * stock.vol
            + math.sin((seed + i) * 0.3) * stock.vol * 0.5
        )
        close = max(0.5, price * (1 + stock.trend + noise))
        open_p = max(0.5, price * (1 + noise * 0.5))
        high = max(open_p, close) * (1 + abs(noise) * 0.3)
        low = min(open_p, close) * (1 - abs(noise) * 0.3)
        volume = int(1_000_000 * (1 + abs(noise) * 5))
        amount = volume * close
        turnover_rate = round(0.5 + abs(noise) * 10, 2)
        bars.append((d, round(open_p, 2), round(high, 2), round(low, 2), round(close, 2),
                     volume, round(amount, 0), turnover_rate))
        price = close
    return bars
