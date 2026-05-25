"""潜力股扫描器 — 三层漏斗 + AI 终审

参考 myhhub/stock（12.6k stars）的成熟策略，融合 WorldQuant Alpha 思路。

## 三层漏斗架构

**Tier 1（快·技术海选 30s-3min）**：5500 只 → 候选池 → Tier-1 (~30 只)
- 6 维度技术评分 + 11 种经典策略 + 交易计划

**Tier 2（中·基本面+资金面过滤 10-30s）**：Tier-1 → Tier-2 (~10-15 只)
- 一票否决：ST / 流通市值<30亿 / 上市<60天 / 龙虎榜异动卖出
- 基本面调整分：PE/盘子/主力资金净流入/龙虎榜机构

**Tier 3（慢·LLM 终审 1-3min）**：Tier-2 → 最终列表 (~5-8 只)
- 每只调用 SuperAnalystAgent 多工具综合分析
- 仅 LLM 给 BUY 且 confidence ≥ 65 的入选
- LLM 完整分析结果直接显示在卡片，无需再点单股分析

## 6 大维度（技术评分，最高 100 分）

1. 趋势维度（20分）：均线排列、MA金叉、价格位置
2. 动量维度（15分）：RSI、MACD、KDJ
3. 量能维度（20分）：放量、量价配合、量比
4. 形态维度（15分）：突破、回踩、底部反转、强势整理
5. 资金维度（15分）：成交额连续放大、龙虎榜暗示
6. 综合维度（15分）：波动率、相对大盘强度、价格位置

## 11 种经典策略（独立打分 + 标签）

1. 放量上涨（涨幅 < 9.5% + 成交额 ≥ 2亿 + 量比 ≥ 2）
2. 均线多头（MA30 向上 + 当前 MA30 比 30 日前涨 20%+）
3. 停机坪（近 15 日有放量大涨，之后小幅高开窄幅整理）
4. 回踩年线（年线之上回踩，缩量企稳）
5. 突破平台（60 日内突破 60 日均线 + 放量）
6. 海龟交易（突破 60 日最高价）
7. 高而窄旗形（10-24 日内连续两天涨幅 9.5%+，今日回到高位）
8. 低 ATR 成长（10 日最高/最低收盘价 ≥ 1.1）
9. 多头排列（MA5>MA10>MA20>MA60，4 线多头）
10. 超跌反弹（RSI 从超卖反弹到 30+）
11. 突破颈线（W 底、双底形态突破）
"""
from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from apps.api.app.services import market_service
from apps.api.app.services import fundamental_service

log = logging.getLogger("quant.scanner")

# 缓存（5 分钟）
_scan_cache: dict = {}
_scan_ts: float = 0.0
_CACHE_TTL = 300

# K 线缓存（同一次扫描内复用，TTL 5 分钟，扫描期间避免重复拉取）
_kline_cache: dict[str, tuple[float, list[dict]]] = {}
_KLINE_TTL = 300
_MAX_KLINE_CACHE = 600  # 防止内存无限膨胀


def _get_kline_cached(symbol: str) -> list[dict]:
    """带 TTL + 容量上限的 K 线缓存"""
    ts, bars = _kline_cache.get(symbol, (0, None))
    if bars is not None and (time.monotonic() - ts) < _KLINE_TTL:
        return bars
    bars = market_service.get_kline(symbol, period="daily", count=120)
    if bars:
        # 容量淘汰：超过上限时删除最早的条目
        if len(_kline_cache) >= _MAX_KLINE_CACHE:
            oldest_key = min(_kline_cache, key=lambda k: _kline_cache[k][0])
            _kline_cache.pop(oldest_key, None)
        _kline_cache[symbol] = (time.monotonic(), bars)
    return bars or []


# ---------------------------------------------------------------------------
# 技术指标计算工具
# ---------------------------------------------------------------------------

def _ma(prices: list[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    return round(sum(prices[-period:]) / period, 3)


def _ema(prices: list[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    e = prices[0]
    for p in prices[1:]:
        e = p * k + e * (1 - k)
    return round(e, 4)


def _ema_series(prices: list[float], period: int) -> list[float]:
    """计算 EMA 序列（与每个收盘价对齐）"""
    if not prices:
        return []
    k = 2 / (period + 1)
    out = [prices[0]]
    for p in prices[1:]:
        out.append(p * k + out[-1] * (1 - k))
    return out


def _macd(prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (DIF, DEA, HIST, DIF_prev) 标准 MACD(12,26,9)"""
    if len(prices) < slow:
        return None, None, None, None
    ema_fast = _ema_series(prices, fast)
    ema_slow = _ema_series(prices, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = _ema_series(dif, signal)
    hist = [(d - e) * 2 for d, e in zip(dif, dea)]
    dif_prev = round(dif[-2], 4) if len(dif) >= 2 else None
    return round(dif[-1], 4), round(dea[-1], 4), round(hist[-1], 4), dif_prev


def _rsi(prices: list[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 2)


def _kdj(highs: list[float], lows: list[float], closes: list[float], period: int = 9):
    if len(closes) < period:
        return None, None, None
    h9 = max(highs[-period:])
    l9 = min(lows[-period:])
    if h9 == l9:
        return 50.0, 50.0, 50.0
    rsv = (closes[-1] - l9) / (h9 - l9) * 100
    k = round(rsv / 3 + 50 * 2 / 3, 2)
    d = round(k / 3 + 50 * 2 / 3, 2)
    j = round(3 * k - 2 * d, 2)
    return k, d, j


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    """平均真实波幅"""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1]),
        )
        trs.append(tr)
    return round(sum(trs[-period:]) / period, 4)


# ---------------------------------------------------------------------------
# 11 种经典策略检测
# ---------------------------------------------------------------------------

def _strategy_volume_surge_up(closes, opens, amounts, today_pct):
    """1. 放量上涨：涨幅 < 9.5% 且收>开，成交额 ≥ 2亿，量比 ≥ 2"""
    if len(closes) < 6 or len(amounts) < 6:
        return False, None
    if today_pct >= 9.5 or today_pct <= 2:
        return False, None
    if closes[-1] <= opens[-1]:
        return False, None
    today_amt = amounts[-1]
    avg_5d = sum(amounts[-6:-1]) / 5
    if today_amt < 2e8:
        return False, None
    if avg_5d <= 0 or today_amt / avg_5d < 2.0:
        return False, None
    return True, f"放量上涨（涨{today_pct:.1f}%，成交{today_amt/1e8:.1f}亿，量比{today_amt/avg_5d:.1f}×）"


def _strategy_ma_bull(closes):
    """2. 均线多头：MA30 向上 + (今日MA30/30日前MA30) > 1.2"""
    if len(closes) < 60:
        return False, None
    ma30_today = sum(closes[-30:]) / 30
    ma30_30d_ago = sum(closes[-60:-30]) / 30
    ma30_20d_ago = sum(closes[-50:-20]) / 30
    ma30_10d_ago = sum(closes[-40:-10]) / 30
    if not (ma30_30d_ago < ma30_20d_ago < ma30_10d_ago < ma30_today):
        return False, None
    if ma30_today / ma30_30d_ago < 1.2:
        return False, None
    return True, f"均线多头（30日MA从{ma30_30d_ago:.2f}涨至{ma30_today:.2f}，+{(ma30_today/ma30_30d_ago-1)*100:.1f}%）"


def _strategy_helipad(closes, opens, highs, lows, amounts):
    """3. 停机坪：近 15 日有大涨放量，之后高开小阳"""
    if len(closes) < 18:
        return False, None
    # 寻找近 15 日内的放量大涨日
    surge_idx = None
    for i in range(-15, -3):
        if i + 1 < -len(closes):
            continue
        prev_close = closes[i-1] if i > -len(closes) else closes[i]
        pct = (closes[i] - prev_close) / prev_close * 100 if prev_close else 0
        if pct < 9.5 or pct > 11:
            continue
        avg_5d = sum(amounts[max(i-5, -len(amounts)):i]) / 5 if i > -len(amounts) + 5 else 0
        if avg_5d > 0 and amounts[i] / avg_5d >= 2:
            surge_idx = i
            break
    if surge_idx is None:
        return False, None
    # 之后 1-3 日小幅高开
    if surge_idx >= -3:
        for j in range(surge_idx+1, 0):
            if j >= len(closes):
                break
            if opens[j] <= closes[j-1]:
                return False, None
            if closes[j] <= opens[j]:
                return False, None
            if abs(closes[j] - opens[j]) / opens[j] >= 0.03:
                return False, None
        return True, "停机坪（大涨后窄幅整理）"
    return False, None


def _strategy_pullback_yearline(closes):
    """4. 回踩年线：250 日均线之上回踩"""
    if len(closes) < 250:
        return False, None
    ma250 = sum(closes[-250:]) / 250
    current = closes[-1]
    if current < ma250:
        return False, None
    # 当前距 MA250 在 -2% ~ +5% 之间（回踩区）
    gap = (current - ma250) / ma250
    if not (-0.02 <= gap <= 0.05):
        return False, None
    # 60 日内有突破年线
    n_len = len(closes)
    for j in range(max(250, n_len - 60), n_len):
        ma_prev = sum(closes[j-250:j]) / 250
        ma_curr = sum(closes[j-249:j+1]) / 250
        if closes[j-1] < ma_prev and closes[j] > ma_curr:
            return True, f"回踩年线（MA250={ma250:.2f}，当前距{gap*100:+.1f}%）"
    return False, None



def _strategy_breakout_platform(closes, amounts):
    """5. 突破平台：60 日内突破 60 日均线 + 当日放量"""
    if len(closes) < 60 or len(amounts) < 6:
        return False, None
    ma60 = sum(closes[-60:]) / 60
    if closes[-1] < ma60 or closes[-2] >= ma60:
        # 必须是今日突破或近期突破
        # 检查近 3 日是否有突破
        broke = False
        for j in range(-3, 0):
            if abs(j) > len(closes) - 60:
                continue
            ma_j = sum(closes[j-59:j+1]) / 60
            ma_jm1 = sum(closes[j-60:j]) / 60 if abs(j-1) <= len(closes) - 60 else None
            if ma_jm1 and closes[j-1] < ma_jm1 and closes[j] > ma_j:
                broke = True
                break
        if not broke:
            return False, None
    avg_5d = sum(amounts[-6:-1]) / 5
    if avg_5d <= 0 or amounts[-1] / avg_5d < 1.5:
        return False, None
    return True, f"突破平台（站上MA60={ma60:.2f}，量比{amounts[-1]/avg_5d:.1f}×）"


def _strategy_turtle(closes):
    """6. 海龟交易：突破 60 日最高收盘价"""
    if len(closes) < 60:
        return False, None
    max_60 = max(closes[-60:-1])
    if closes[-1] >= max_60 * 1.005:
        return True, f"海龟突破（突破60日新高{max_60:.2f}，现价{closes[-1]:.2f}）"
    return False, None


def _strategy_high_tight_flag(closes, lows):
    """7. 高而窄旗形：10-24 日前的最低价的 1.9 倍 + 之前两天连续 9.5%+ 涨幅"""
    if len(closes) < 25:
        return False, None
    # 之前 24-10 日的最低价
    min_low = min(lows[-25:-9])
    if closes[-1] / min_low < 1.9:
        return False, None
    # 之前 24-10 日连续两天涨幅 ≥ 9.5%
    has_double_jump = False
    for i in range(-24, -10):
        if abs(i) >= len(closes) - 1:
            continue
        c_prev = closes[i-1]
        c_curr = closes[i]
        c_next = closes[i+1]
        if c_prev > 0 and c_curr > 0:
            pct1 = (c_curr - c_prev) / c_prev * 100
            pct2 = (c_next - c_curr) / c_curr * 100
            if pct1 >= 9.5 and pct2 >= 9.5:
                has_double_jump = True
                break
    if not has_double_jump:
        return False, None
    return True, f"高而窄旗形（{closes[-1]/min_low:.1f}倍，连续涨停后整理）"


def _strategy_low_atr_growth(closes):
    """8. 低 ATR 成长：10 日最高/最低收盘价 ≥ 1.1"""
    if len(closes) < 10:
        return False, None
    high_10 = max(closes[-10:])
    low_10 = min(closes[-10:])
    if low_10 <= 0:
        return False, None
    ratio = high_10 / low_10
    if ratio < 1.10:
        return False, None
    return True, f"低ATR成长（10日波幅{(ratio-1)*100:.1f}%）"


def _strategy_four_ma_bull(closes):
    """9. 四线多头排列：MA5>MA10>MA20>MA60"""
    if len(closes) < 60:
        return False, None
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    if not (ma5 > ma10 > ma20 > ma60):
        return False, None
    return True, f"四线多头（MA5>{ma5:.2f}>MA10>{ma10:.2f}>MA20>{ma20:.2f}>MA60>{ma60:.2f}）"


def _strategy_oversold_bounce(closes):
    """10. 超跌反弹：RSI 从超卖回升"""
    if len(closes) < 20:
        return False, None
    rsi_now = _rsi(closes, 14)
    rsi_5d_ago = _rsi(closes[:-5], 14)
    if rsi_now is None or rsi_5d_ago is None:
        return False, None
    if rsi_5d_ago < 30 and rsi_now > 35 and rsi_now < 60:
        return True, f"超跌反弹（RSI从{rsi_5d_ago:.1f}回升至{rsi_now:.1f}）"
    return False, None


def _strategy_double_bottom(closes, lows):
    """11. 突破颈线（W 底）：30日内两次低点 + 突破颈线"""
    if len(closes) < 30:
        return False, None
    # 找 30 日内的两个低点
    section = lows[-30:]
    min_idx = section.index(min(section))
    if min_idx == 0 or min_idx >= 28:
        return False, None
    # 第一个低点之前找另一个低点
    left = section[:min_idx]
    right = section[min_idx+1:]
    if not left or not right:
        return False, None
    left_low = min(left)
    right_low = min(right)
    # 双底要求两个低点接近（差距 < 5%）
    if abs(left_low - right_low) / max(left_low, right_low) > 0.05:
        return False, None
    # 颈线 = 两底之间的最高点
    between = section[min_idx:]
    neckline = max(between)
    # 当前价突破颈线
    if closes[-1] < neckline * 1.005:
        return False, None
    return True, f"W底突破（双底约{left_low:.2f}/{right_low:.2f}，颈线{neckline:.2f}）"


# ---------------------------------------------------------------------------
# 6 大维度评分系统
# ---------------------------------------------------------------------------

def _score_signals(bars: list[dict], current_quote: dict) -> tuple[int, dict, list[dict], list[str], list[dict], dict]:
    """
    返回 (总分, 维度分数, 触发的信号列表, 标签, 经典策略列表, 技术指标)
    """
    if not bars or len(bars) < 30:
        return 0, {}, [], [], [], {}

    closes = [float(b.get("close", 0)) for b in bars]
    opens  = [float(b.get("open", 0)) for b in bars]
    highs  = [float(b.get("high", 0)) for b in bars]
    lows   = [float(b.get("low", 0)) for b in bars]
    amounts = [float(b.get("amount", b.get("volume", 0))) for b in bars]
    n = len(closes)

    today_pct = float(current_quote.get("change_pct", 0))
    today_turnover = float(current_quote.get("turnover", 0)) or amounts[-1]

    # 基础指标
    ma5  = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    ma5_prev  = _ma(closes[:-1], 5)
    ma10_prev = _ma(closes[:-1], 10)
    ma20_prev = _ma(closes[:-1], 20)

    rsi14 = _rsi(closes, 14)
    rsi_5d_ago = _rsi(closes[:-5], 14) if n >= 19 else None

    # 标准 MACD(12,26,9)
    macd_dif, macd_dea, macd_hist, macd_dif_prev = _macd(closes, 12, 26, 9)
    # 上一根的 DEA（用于判断金叉）
    macd_dea_prev = None
    if n >= 27:
        _, _dea_prev, _, _ = _macd(closes[:-1], 12, 26, 9)
        macd_dea_prev = _dea_prev

    kdj_k, kdj_d, kdj_j = _kdj(highs, lows, closes)
    atr14 = _atr(highs, lows, closes, 14)

    # 量能
    amt_5d_avg = sum(amounts[-6:-1]) / 5 if n >= 6 else None
    amt_20d_avg = sum(amounts[-20:]) / 20 if n >= 20 else None
    vol_ratio = round(today_turnover / amt_5d_avg, 2) if amt_5d_avg and amt_5d_avg > 0 else None
    vol_ratio_20d = round(today_turnover / amt_20d_avg, 2) if amt_20d_avg and amt_20d_avg > 0 else None

    # 价格位置
    high_20 = max(highs[-20:])
    low_20 = min(lows[-20:])
    high_60 = max(highs[-60:]) if n >= 60 else max(highs)
    low_60 = min(lows[-60:]) if n >= 60 else min(lows)
    current = closes[-1]
    # 价格位置（一字板时设为 100，避免被当成中性区域加分）
    if high_20 == low_20:
        pos_in_20d = 100  # 一字板/连续涨停
    else:
        pos_in_20d = round((current - low_20) / (high_20 - low_20) * 100, 1)

    # 涨跌幅
    ret_5d  = round((current - closes[-5]) / closes[-5] * 100, 2) if n >= 5 and closes[-5] else 0
    ret_20d = round((current - closes[-20]) / closes[-20] * 100, 2) if n >= 20 and closes[-20] else 0

    # 波动率
    vol_20d_pct = None
    if n >= 20:
        rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(n-19, n) if closes[i-1]]
        if rets:
            avg = sum(rets) / len(rets)
            vol_20d_pct = round(math.sqrt(sum((r-avg)**2 for r in rets) / len(rets)) * 100, 2)

    # ============================================================
    # 维度评分
    # ============================================================
    dim_scores = {"trend": 0, "momentum": 0, "volume": 0, "pattern": 0, "capital": 0, "comprehensive": 0}
    signals: list[dict] = []
    tags: list[str] = []

    # ---- 1. 趋势维度（20分）----
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            dim_scores["trend"] += 8
            signals.append({"type": "trend", "dim": "trend", "strength": "strong",
                          "desc": f"多头排列 MA5({ma5})>MA10({ma10})>MA20({ma20})"})
            tags.append("多头排列")
            if ma60 and ma20 > ma60:
                dim_scores["trend"] += 4
                tags.append("四线多头")
        # 金叉
        if ma5_prev and ma10_prev and ma5_prev <= ma10_prev and ma5 > ma10:
            dim_scores["trend"] += 5
            signals.append({"type": "ma_cross", "dim": "trend", "strength": "strong",
                          "desc": f"MA5 金叉 MA10（{ma5_prev}≤{ma10_prev} → {ma5}>{ma10}）"})
            tags.append("MA5金叉")
        if ma10_prev and ma20_prev and ma10_prev <= ma20_prev and ma10 and ma20 and ma10 > ma20:
            dim_scores["trend"] += 3
            tags.append("MA10金叉")

    # ---- 2. 动量维度（15分）----
    if rsi14 is not None:
        if 35 <= rsi14 <= 60:
            dim_scores["momentum"] += 5
            signals.append({"type": "rsi", "dim": "momentum", "strength": "good",
                          "desc": f"RSI={rsi14:.1f}（中性偏强区，健康）"})
        elif rsi14 < 30:
            dim_scores["momentum"] += 3
            signals.append({"type": "rsi", "dim": "momentum", "strength": "ok",
                          "desc": f"RSI={rsi14:.1f}（超卖反弹机会）"})

    if rsi_5d_ago is not None and rsi14 is not None:
        if rsi_5d_ago < 30 and rsi14 > 35:
            dim_scores["momentum"] += 4
            signals.append({"type": "rsi_bounce", "dim": "momentum", "strength": "strong",
                          "desc": f"RSI 从 {rsi_5d_ago:.1f} 反弹至 {rsi14:.1f}（超跌反弹）"})
            tags.append("超跌反弹")

    if macd_dif is not None and macd_dea is not None:
        if macd_dif > macd_dea and macd_hist > 0:
            dim_scores["momentum"] += 3
            signals.append({"type": "macd", "dim": "momentum", "strength": "good",
                          "desc": f"MACD 多头 (DIF={macd_dif} > DEA={macd_dea}，红柱)"})
            tags.append("MACD多头")
        # 真实金叉判定：上一根 DIF<=DEA，本根 DIF>DEA
        if (macd_dif_prev is not None and macd_dea_prev is not None
                and macd_dif_prev <= macd_dea_prev and macd_dif > macd_dea):
            dim_scores["momentum"] += 3
            signals.append({"type": "macd_cross", "dim": "momentum", "strength": "strong",
                          "desc": f"MACD 金叉（DIF 上穿 DEA，{macd_dif_prev}→{macd_dif}）"})
            tags.append("MACD金叉")

    # ---- 3. 量能维度（20分）----
    if vol_ratio is not None:
        if 1.5 <= vol_ratio <= 4 and today_pct > 0:
            dim_scores["volume"] += 12
            signals.append({"type": "volume", "dim": "volume", "strength": "strong",
                          "desc": f"放量上涨（量比 {vol_ratio:.1f}× + 涨 {today_pct:.2f}%）"})
            tags.append("放量上涨")
        elif vol_ratio > 4:
            dim_scores["volume"] += 4
            signals.append({"type": "volume", "dim": "volume", "strength": "warn",
                          "desc": f"成交量异常 ({vol_ratio:.1f}×)，警惕"})
        elif 1.0 <= vol_ratio < 1.5 and today_pct > 0:
            dim_scores["volume"] += 5
            signals.append({"type": "volume", "dim": "volume", "strength": "ok",
                          "desc": f"温和放量（量比 {vol_ratio:.1f}×）"})

    # 连续放量
    if n >= 6:
        recent_amts = amounts[-3:]
        prev_amts = amounts[-6:-3]
        if sum(recent_amts) > sum(prev_amts) * 1.3 and all(closes[-i] > closes[-i-1] for i in range(1, 4)):
            dim_scores["volume"] += 5
            signals.append({"type": "vol_growing", "dim": "volume", "strength": "good",
                          "desc": "连续3日放量上涨（资金持续流入）"})
            tags.append("连续放量")

    # 量价配合
    if today_pct > 2 and vol_ratio_20d and vol_ratio_20d > 1.2:
        dim_scores["volume"] += 3

    # ---- 4. 形态维度（15分）----
    # 突破
    if n >= 21:
        prev_high_20 = max(highs[-21:-1])
        if current > prev_high_20 * 1.005:
            dim_scores["pattern"] += 8
            signals.append({"type": "breakout", "dim": "pattern", "strength": "strong",
                          "desc": f"突破 20 日高点 {prev_high_20:.2f}（现价 {current:.2f}）"})
            tags.append("突破高点")
        elif ma20 and abs(current - ma20) / ma20 < 0.02 and current > ma20 * 0.99:
            dim_scores["pattern"] += 5
            signals.append({"type": "support", "dim": "pattern", "strength": "good",
                          "desc": f"回踩 MA20({ma20:.2f}) 不破"})
            tags.append("回踩MA20")

    # 海龟突破
    if n >= 60 and current >= max(closes[-60:-1]) * 1.005:
        dim_scores["pattern"] += 5
        tags.append("60日新高")

    # KDJ 金叉
    if kdj_k is not None and kdj_d is not None:
        if 20 < kdj_k < 80 and kdj_k > kdj_d:
            dim_scores["pattern"] += 2

    # ---- 5. 资金维度（15分）----
    if today_turnover >= 5e8:
        dim_scores["capital"] += 5
    elif today_turnover >= 2e8:
        dim_scores["capital"] += 3

    # 5 日成交额连续放大
    if n >= 5 and len(amounts) >= 5:
        if amounts[-1] > amounts[-2] > amounts[-3] and amounts[-1] > sum(amounts[-5:-2])/3 * 1.2:
            dim_scores["capital"] += 5
            signals.append({"type": "capital_inflow", "dim": "capital", "strength": "good",
                          "desc": "成交额连续放大（资金加速流入）"})
            tags.append("资金流入")

    # 大单成交（用 amount/volume 估算，简化处理）
    if vol_ratio and vol_ratio > 2 and today_pct > 1:
        dim_scores["capital"] += 3

    # ---- 6. 综合维度（15分）----
    # 价格位置
    if 30 <= pos_in_20d <= 70:
        dim_scores["comprehensive"] += 5
        signals.append({"type": "position", "dim": "comprehensive", "strength": "good",
                      "desc": f"价格在20日区间 {pos_in_20d}% 位置（健康）"})
    elif pos_in_20d < 30:
        dim_scores["comprehensive"] += 3
        signals.append({"type": "position", "dim": "comprehensive", "strength": "ok",
                      "desc": f"价格在20日区间低位 {pos_in_20d}%（潜在反转）"})

    # 价格强度
    if 0 < today_pct <= 5:
        dim_scores["comprehensive"] += 3
    if 2 < ret_5d <= 12:
        dim_scores["comprehensive"] += 3

    # 波动率合理
    if vol_20d_pct and 1.0 <= vol_20d_pct <= 3.5:
        dim_scores["comprehensive"] += 2
    elif vol_20d_pct and vol_20d_pct > 5:
        dim_scores["comprehensive"] -= 2  # 高波动扣分

    # ============================================================
    # 11 种经典策略检测
    # ============================================================
    classic_strategies: list[dict] = []

    strategy_funcs = [
        ("放量上涨", _strategy_volume_surge_up, (closes, opens, amounts, today_pct)),
        ("均线多头", _strategy_ma_bull, (closes,)),
        ("停机坪", _strategy_helipad, (closes, opens, highs, lows, amounts)),
        ("回踩年线", _strategy_pullback_yearline, (closes,)),
        ("突破平台", _strategy_breakout_platform, (closes, amounts)),
        ("海龟交易", _strategy_turtle, (closes,)),
        ("高而窄旗形", _strategy_high_tight_flag, (closes, lows)),
        ("低ATR成长", _strategy_low_atr_growth, (closes,)),
        ("四线多头", _strategy_four_ma_bull, (closes,)),
        ("超跌反弹", _strategy_oversold_bounce, (closes,)),
        ("双底突破", _strategy_double_bottom, (closes, lows)),
    ]

    for name, fn, args in strategy_funcs:
        try:
            hit, desc = fn(*args)
            if hit:
                classic_strategies.append({"name": name, "desc": desc})
                if name not in tags:
                    tags.append(name)
        except Exception as e:
            log.debug("strategy %s failed: %s", name, e)

    # 经典策略加分（每命中一个加 5 分，但维度满分 100）
    strategy_bonus = min(20, len(classic_strategies) * 5)

    # ============================================================
    # 总分（限制各维度上限）
    # ============================================================
    dim_scores["trend"] = min(20, dim_scores["trend"])
    dim_scores["momentum"] = min(15, dim_scores["momentum"])
    dim_scores["volume"] = min(20, dim_scores["volume"])
    dim_scores["pattern"] = min(15, dim_scores["pattern"])
    dim_scores["capital"] = min(15, dim_scores["capital"])
    dim_scores["comprehensive"] = min(15, max(0, dim_scores["comprehensive"]))

    base_score = sum(dim_scores.values())
    total_score = min(100, base_score + strategy_bonus)

    indicators = {
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "rsi14": rsi14, "rsi_5d_ago": rsi_5d_ago,
        "macd_dif": macd_dif, "macd_dea": macd_dea, "macd_hist": macd_hist,
        "kdj_k": kdj_k, "kdj_d": kdj_d, "kdj_j": kdj_j,
        "atr14": atr14,
        "vol_ratio": vol_ratio, "vol_ratio_20d": vol_ratio_20d,
        "pos_in_20d": pos_in_20d,
        "today_pct": today_pct,
        "ret_5d": ret_5d, "ret_20d": ret_20d,
        "high_20": round(high_20, 2), "low_20": round(low_20, 2),
        "high_60": round(high_60, 2), "low_60": round(low_60, 2),
        "vol_20d_pct": vol_20d_pct,
    }

    return total_score, dim_scores, signals, tags, classic_strategies, indicators


# ---------------------------------------------------------------------------
# 明日交易计划生成器
# ---------------------------------------------------------------------------

def _build_trade_plan(
    bars: list[dict],
    indicators: dict,
    current_price: float,
    score: int,
    strategies: list[dict],
    tags: list[str],
) -> dict:
    """
    根据技术指标 + 形态生成可直接执行的交易计划。

    输出包含：
      - rating          : "强烈推荐 / 推荐 / 观察 / 不建议"
      - entry_low       : 建议买入区间下沿（明日开盘后等回踩这里再买）
      - entry_high      : 建议买入区间上沿（超过这个就追高）
      - stop_loss       : 止损价（跌破这里坚决卖出）
      - target1         : 短线目标（5-10 日）
      - target2         : 中线目标（20-30 日）
      - holding_days    : 建议持有周期（"1-3 日 / 5-10 日 / 1-2 月"）
      - position_pct    : 建议仓位（占总资金的 % 区间）
      - expected_return : 期望收益（按 target1 估算）
      - risk_reward     : 风险收益比（target1 vs stop_loss）
      - reasons         : 看好理由（3-5 条人话）
      - warnings        : 风险提示（1-3 条）
      - tomorrow_plan   : 一句话明日操作建议
    """
    if not bars or current_price <= 0:
        return {}

    closes = [float(b.get("close", 0)) for b in bars]
    highs  = [float(b.get("high", 0)) for b in bars]
    lows   = [float(b.get("low", 0)) for b in bars]
    n = len(closes)

    ma5 = indicators.get("ma5")
    ma10 = indicators.get("ma10")
    ma20 = indicators.get("ma20")
    ma60 = indicators.get("ma60")
    atr14 = indicators.get("atr14") or current_price * 0.02
    rsi14 = indicators.get("rsi14")
    today_pct = indicators.get("today_pct", 0)
    high_20 = indicators.get("high_20", current_price)
    low_20 = indicators.get("low_20", current_price * 0.95)
    high_60 = indicators.get("high_60", high_20)
    pos_in_20d = indicators.get("pos_in_20d", 50)
    vol_20d_pct = indicators.get("vol_20d_pct") or 2.0

    # ---------- 评级 ----------
    if score >= 80:
        rating = "强烈推荐"
    elif score >= 65:
        rating = "推荐"
    elif score >= 50:
        rating = "观察"
    else:
        rating = "不建议"

    # ---------- 买入区间 ----------
    # 短线策略：用 MA5 / MA10 / 当日收盘价的回踩位作为入场参考
    candidates = [current_price * 0.985]
    if ma5: candidates.append(ma5)
    if ma10: candidates.append(ma10 * 1.005)
    # 强势股不要太奢望低吸，弱势股可以等更深回踩
    if today_pct > 5:
        # 涨幅过大，等回踩
        entry_high = round(current_price * 0.998, 2)
        entry_low  = round(min(candidates) * 0.99, 2)
    elif today_pct > 0:
        entry_high = round(current_price * 1.005, 2)
        entry_low  = round(min(candidates), 2)
    else:
        # 下跌日反而可以小仓位低吸
        entry_high = round(current_price * 1.005, 2)
        entry_low  = round(current_price * 0.985, 2)

    # 兜底：买入区间不要太宽
    if entry_high - entry_low < current_price * 0.005:
        entry_low = round(entry_high * 0.99, 2)
    if entry_high - entry_low > current_price * 0.04:
        entry_low = round(entry_high * 0.97, 2)

    entry_mid = round((entry_low + entry_high) / 2, 2)

    # ---------- 止损 ----------
    # 三种止损候选：① ATR 止损（2×ATR） ② MA20 跌破 ③ 20日低点
    stop_candidates = []
    stop_candidates.append(entry_mid - 2 * atr14)
    if ma20 and ma20 < entry_mid:
        stop_candidates.append(ma20 * 0.985)
    if low_20 < entry_mid:
        stop_candidates.append(low_20 * 0.99)
    # 取最高（最近）的那个，避免止损过远
    stop_loss = round(max([s for s in stop_candidates if s > 0] or [entry_mid * 0.93]), 2)
    # 止损不要离买点太远（最大 8%）
    if (entry_mid - stop_loss) / entry_mid > 0.08:
        stop_loss = round(entry_mid * 0.92, 2)
    # 止损不要太近（最少 3%，避免被噪声扫损）
    if (entry_mid - stop_loss) / entry_mid < 0.03:
        stop_loss = round(entry_mid * 0.97, 2)
    # 兜底：止损必须严格低于买入下沿
    if stop_loss >= entry_low:
        stop_loss = round(entry_low * 0.97, 2)

    # ---------- 目标价 ----------
    # target1: 短线（5-10日）= 突破 20 日高点 或 +1×ATR×3
    target1_candidates = [
        entry_mid + 3 * atr14,
        high_20 * 1.02,
    ]
    if today_pct > 5:
        # 已经接近高点，目标稍微保守
        target1 = round(min(target1_candidates), 2)
    else:
        target1 = round(max(target1_candidates), 2)
    # 兜底：短线目标至少高于买点 3%（避免出现负期望收益）
    target1 = max(target1, round(entry_mid * 1.03, 2))

    # target2: 中线（20-30日）= 60日高点 或 +1×ATR×6
    target2_candidates = [
        entry_mid + 6 * atr14,
        high_60 * 1.05,
    ]
    target2 = round(max(target2_candidates), 2)
    # 中线目标必须高于短线目标
    target2 = max(target2, round(target1 * 1.05, 2))

    # ---------- 持有周期 ----------
    has_breakout = any(s["name"] in ("放量上涨", "高而窄旗形", "突破平台", "海龟交易") for s in strategies)
    has_trend = any(s["name"] in ("均线多头", "四线多头", "回踩年线") for s in strategies)
    has_reversal = any(s["name"] in ("超跌反弹", "双底突破") for s in strategies)

    if has_breakout and not has_trend:
        holding_days = "3-7 日（短线突破）"
        time_horizon = "短线"
    elif has_trend:
        holding_days = "10-30 日（趋势跟踪）"
        time_horizon = "中线"
    elif has_reversal:
        holding_days = "5-15 日（反弹波段）"
        time_horizon = "波段"
    else:
        holding_days = "5-10 日"
        time_horizon = "短线"

    # ---------- 建议仓位 ----------
    if rating == "强烈推荐":
        position_pct = "20-30%"
    elif rating == "推荐":
        position_pct = "10-20%"
    elif rating == "观察":
        position_pct = "5-10%"
    else:
        position_pct = "建议跳过"

    # 高波动股票降仓位
    if vol_20d_pct and vol_20d_pct > 4:
        if rating == "强烈推荐":
            position_pct = "10-20%"
        elif rating == "推荐":
            position_pct = "5-10%"

    # ---------- 期望收益 + 风险收益比 ----------
    expected_return = round((target1 - entry_mid) / entry_mid * 100, 2)
    max_loss = round((entry_mid - stop_loss) / entry_mid * 100, 2)
    if max_loss <= 0.1:
        max_loss = 3.0  # 兜底，避免极端情况下风险收益比无穷大
    risk_reward = round(max(0.0, expected_return) / max_loss, 2)

    # ---------- 看好理由 ----------
    reasons = []
    if has_trend:
        reasons.append(f"均线多头排列（MA5>{ma5 or 0:.2f} > MA10 > MA20），趋势已确立")
    if has_breakout:
        reasons.append(f"形态突破信号明确（{'放量上涨' if any(s['name']=='放量上涨' for s in strategies) else '突破平台/高位整理'}）")
    if any(s["name"] == "双底突破" for s in strategies):
        reasons.append("W 底突破颈线，底部反转形态确立")
    if any(s["name"] == "超跌反弹" for s in strategies):
        reasons.append(f"RSI 从超卖区回升至 {rsi14:.0f}，超跌反弹动力充足" if rsi14 else "RSI 超卖反弹")
    if pos_in_20d <= 70 and pos_in_20d >= 30:
        reasons.append(f"价格位于 20 日区间 {pos_in_20d}% 位置，回调风险有限")
    if indicators.get("vol_ratio") and indicators["vol_ratio"] > 1.5:
        reasons.append(f"今日量比 {indicators['vol_ratio']:.1f}×，资金关注度提升")
    if not reasons:
        reasons.append("综合技术指标正面，短期具备上涨空间")
    reasons = reasons[:5]

    # ---------- 风险提示 ----------
    warnings = []
    if today_pct > 7:
        warnings.append(f"今日涨幅 {today_pct:.1f}%，明日有回踩需求，避免追高")
    if rsi14 and rsi14 > 75:
        warnings.append(f"RSI {rsi14:.0f} 进入超买区，短期可能回落")
    if pos_in_20d > 90:
        warnings.append("价格已贴近 20 日高点，突破不成立则面临回落")
    if vol_20d_pct and vol_20d_pct > 4:
        warnings.append(f"近 20 日波动率 {vol_20d_pct:.1f}%，振幅较大，注意止损纪律")
    if not has_trend and not has_breakout:
        warnings.append("缺乏明确趋势/突破信号，仅作短线博弈")
    warnings = warnings[:3]

    # ---------- 明日操作 ----------
    if rating == "不建议":
        tomorrow_plan = "明日不建议买入，等待更好的机会"
    elif today_pct > 7:
        tomorrow_plan = f"明日观察，若回踩 {entry_low:.2f}-{entry_high:.2f} 区间且不破 MA5 可分批介入"
    elif has_breakout:
        tomorrow_plan = f"明日开盘 {entry_low:.2f}-{entry_high:.2f} 区间挂单买入，跌破 {stop_loss:.2f} 止损"
    elif has_trend:
        tomorrow_plan = f"明日回踩 {entry_low:.2f} 附近分批买入，短期目标 {target1:.2f}"
    else:
        tomorrow_plan = f"明日 {entry_low:.2f}-{entry_high:.2f} 区间小仓位试探，止损 {stop_loss:.2f}"

    return {
        "rating": rating,
        "time_horizon": time_horizon,
        "holding_days": holding_days,
        "position_pct": position_pct,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_mid": entry_mid,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "expected_return_pct": expected_return,
        "max_loss_pct": max_loss,
        "risk_reward": risk_reward,
        "reasons": reasons,
        "warnings": warnings,
        "tomorrow_plan": tomorrow_plan,
    }


# ---------------------------------------------------------------------------
# 候选股快速过滤
# ---------------------------------------------------------------------------

def _filter_candidates(
    all_quotes: list[dict],
    *,
    exclude_st: bool = True,
    exclude_new: bool = True,
    min_price: float = 1.0,
    max_price: float = 500.0,
    min_today_pct: float = -3.0,
    max_today_pct: float = 9.5,
    min_turnover: float = 5e7,
) -> list[dict]:
    candidates = []
    for q in all_quotes:
        name = q.get("name", "")
        price = q.get("price", 0)
        pct = q.get("change_pct", 0)
        turnover = q.get("turnover", 0)

        if exclude_st and ("ST" in name or "*ST" in name):
            continue
        if exclude_new and (name.startswith("N") or name.startswith("C")):
            continue
        if not (min_price <= price <= max_price):
            continue
        if not (min_today_pct <= pct <= max_today_pct):
            continue
        if turnover < min_turnover:
            continue
        candidates.append(q)
    return candidates


# ---------------------------------------------------------------------------
# 主扫描函数
# ---------------------------------------------------------------------------

def scan_potential_stocks(
    *,
    top_n: int = 30,
    min_score: int = 50,
    candidate_pool: int = 120,
    use_cache: bool = True,
    filter_params: Optional[dict] = None,
    required_strategies: Optional[list[str]] = None,
    enable_fundamental: bool = True,
    enable_llm: bool = True,
    llm_top_n: int = 12,
    progress_callback=None,
) -> dict:
    """三层漏斗扫描：技术海选 → 基本面过滤 → LLM 终审。

    Args:
        top_n: 最终输出数量
        min_score: Tier-1 最低技术分
        candidate_pool: Tier-1 深度分析候选池大小
        enable_fundamental: 是否启用 Tier-2 基本面过滤
        enable_llm: 是否启用 Tier-3 LLM 终审
        llm_top_n: 进入 Tier-3 的最大数量（每只一次 LLM 调用，控制耗时）
        progress_callback: 进度回调（可选）
        required_strategies: 必须命中的策略名列表
    """
    global _scan_cache, _scan_ts
    from datetime import date as _date

    cache_key = f"{_date.today()}_top{top_n}_min{min_score}_pool{candidate_pool}_req{required_strategies}_f{enable_fundamental}_l{enable_llm}"
    if use_cache and _scan_cache.get(cache_key) and (time.monotonic() - _scan_ts < _CACHE_TTL):
        result = dict(_scan_cache[cache_key])
        result["cached"] = True
        return result

    t0 = time.monotonic()

    all_quotes = market_service.get_all_quotes_snapshot()
    if not all_quotes:
        return {"error": "全市场数据未就绪", "results": []}

    market_status = _compute_market_status(all_quotes)

    # ============================================================
    # Tier 1：技术海选
    # ============================================================
    if progress_callback:
        progress_callback("tier1_start", {"total": len(all_quotes)})

    params = filter_params or {}
    candidates = _filter_candidates(all_quotes, **params)

    def _candidate_score(q):
        pct = q.get("change_pct", 0)
        pct_score = pct if 0 < pct <= 5 else (pct - 5 if pct > 5 else 0)
        return pct_score * 5 + math.log10(max(q.get("turnover", 1), 1))

    candidates.sort(key=_candidate_score, reverse=True)
    pool = candidates[:candidate_pool]

    log.info("scanner T1: 全市场 %d → 候选 %d → 深度分析 %d",
             len(all_quotes), len(candidates), len(pool))

    def _analyze_one(quote: dict) -> Optional[dict]:
        try:
            symbol = quote["symbol"]
            bars = _get_kline_cached(symbol)
            if not bars or len(bars) < 30:
                return None
            score, dim_scores, signals, tags, strategies, indicators = _score_signals(bars, quote)

            if required_strategies:
                hit_names = {s["name"] for s in strategies}
                if not any(req in hit_names for req in required_strategies):
                    return None

            if score < min_score:
                return None

            current_price = quote.get("price", 0) or (bars[-1].get("close") if bars else 0)
            trade_plan = _build_trade_plan(
                bars, indicators, current_price, score, strategies, tags
            )

            return {
                "symbol": symbol,
                "name": quote.get("name", symbol),
                "price": quote.get("price", 0),
                "change_pct": quote.get("change_pct", 0),
                "turnover": quote.get("turnover", 0),
                "score": score,
                "tier1_score": score,
                "dim_scores": dim_scores,
                "signals": signals,
                "tags": tags,
                "strategies": strategies,
                "indicators": indicators,
                "trade_plan": trade_plan,
            }
        except Exception as e:
            log.debug("T1 scan %s failed: %s", quote.get("symbol"), e)
            return None

    tier1_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=30, thread_name_prefix="scanner-t1") as ex:
        futures = [ex.submit(_analyze_one, q) for q in pool]
        for fut in as_completed(futures):
            try:
                r = fut.result(timeout=30)
                if r:
                    tier1_results.append(r)
            except Exception:
                pass

    tier1_results.sort(key=lambda x: x["score"], reverse=True)
    # 取前 top_n*2 作为 Tier-2 输入（给 Tier-2/3 留淘汰空间）
    tier1_top = tier1_results[: max(top_n * 2, 30)]

    log.info("scanner T1 完成：%d 只通过技术评分", len(tier1_top))
    if progress_callback:
        progress_callback("tier1_done", {"count": len(tier1_top)})

    # ============================================================
    # Tier 2：基本面 + 资金面 过滤
    # ============================================================
    tier2_results = tier1_top
    if enable_fundamental and tier1_top:
        if progress_callback:
            progress_callback("tier2_start", {"count": len(tier1_top)})

        def _fund_one(r: dict) -> Optional[dict]:
            try:
                ev = fundamental_service.evaluate_fundamental(r["symbol"], r.get("name", ""))
                if ev["hard_blocks"]:
                    log.debug("T2 淘汰 %s: %s", r["symbol"], ev["hard_blocks"])
                    return None
                # 不再修改 r["score"]（Tier-1 技术分保持独立），
                # 而是把基本面/资金面分数作为独立维度附加
                r2 = dict(r)
                r2["fundamental"] = {
                    "quality": ev["quality"],          # 0-25
                    "flow_score": ev["flow_score"],    # 0-25
                    "quality_items": ev["quality_items"],
                    "flow_items": ev["flow_items"],
                    "info": ev["info"],
                    "fund_flow": ev["fund_flow"],
                    "lhb": ev["lhb"],
                }
                return r2
            except Exception as e:
                log.debug("T2 fund %s failed: %s", r.get("symbol"), e)
                # 评估失败时不淘汰，只是没有基本面分
                return r

        with ThreadPoolExecutor(max_workers=10, thread_name_prefix="scanner-t2") as ex:
            futures = [ex.submit(_fund_one, r) for r in tier1_top]
            tier2_results = []
            for fut in as_completed(futures):
                try:
                    r = fut.result(timeout=30)
                    if r:
                        tier2_results.append(r)
                except Exception:
                    pass

        tier2_results.sort(key=lambda x: x["score"], reverse=True)  # 按 Tier-1 技术分排序
        log.info("scanner T2 完成：%d → %d", len(tier1_top), len(tier2_results))
        if progress_callback:
            progress_callback("tier2_done", {"count": len(tier2_results)})

    # ============================================================
    # Tier 3：LLM 终审（只对 Tier-2 顶部做 LLM 分析）
    # ============================================================
    final_results = tier2_results
    rejected_list: list[dict] = []
    # 自动检测：LLM 不可用时跳过 Tier-3
    if enable_llm:
        try:
            from libs.llm_analyst.llm_client import LLMClient
            if not LLMClient().is_llm_available():
                log.info("LLM 未配置，自动跳过 Tier-3")
                enable_llm = False
        except Exception:
            enable_llm = False

    if enable_llm and tier2_results:
        llm_candidates = tier2_results[:llm_top_n]
        if progress_callback:
            progress_callback("tier3_start", {"count": len(llm_candidates)})

        def _llm_one(r: dict) -> Optional[dict]:
            try:
                # 调用 SuperAnalystAgent 做综合决策
                # 关键改动：把 Tier-1（技术）+ Tier-2（基本面）的数据全部传给 LLM，
                # 这样 LLM 不需要重新调工具拉数据，且看到的是和扫描器一致的指标
                from libs.agents.super_analyst import SuperAnalystAgent
                from libs.agents.skills import ToolResult

                bars = _get_kline_cached(r["symbol"]) or []
                quote_data = {
                    "symbol": r["symbol"],
                    "name": r.get("name", ""),
                    "price": r.get("price"),
                    "change_pct": r.get("change_pct"),
                    "turnover": r.get("turnover"),
                }
                # 把 Tier-1 indicators 重新组织成 Agent 期望的 feature dict
                ind = r.get("indicators") or {}
                feat = {
                    "ma5": ind.get("ma5"), "ma10": ind.get("ma10"),
                    "ma20": ind.get("ma20"), "ma60": ind.get("ma60"),
                    "rsi14": ind.get("rsi14"),
                    "macd_dif": ind.get("macd_dif"), "macd_dea": ind.get("macd_dea"),
                    "macd_hist": ind.get("macd_hist"),
                    "kdj_k": ind.get("kdj_k"), "kdj_d": ind.get("kdj_d"), "kdj_j": ind.get("kdj_j"),
                    "vol_ratio": ind.get("vol_ratio"),
                    "vol_20d": ind.get("vol_20d_pct"),
                    "ret_1d": r.get("change_pct"),
                    "ret_5d": ind.get("ret_5d"),
                    "ret_20d": ind.get("ret_20d"),
                    "high_20": ind.get("high_20"), "low_20": ind.get("low_20"),
                    "high_60": ind.get("high_60"), "low_60": ind.get("low_60"),
                    "pos_in_20d": ind.get("pos_in_20d"),
                }
                pattern_data = {
                    "trend_20d": "上升" if ind.get("ret_20d", 0) > 5 else ("下降" if ind.get("ret_20d", 0) < -5 else "震荡"),
                    "above_ma20": (ind.get("ma20") or 0) > 0 and r.get("price", 0) > (ind.get("ma20") or 0),
                    "patterns": [{"name": s["name"], "desc": s["desc"]} for s in r.get("strategies", [])],
                }

                # 用 Tier-2 数据补充资金面
                fund_block = r.get("fundamental") or {}
                f_info = fund_block.get("info") or {}
                f_flow = fund_block.get("fund_flow") or {}
                # 把基本面+资金面整合成 LLM 可读的"intelligence"信号
                intelligence_text = []
                if f_info.get("pe") is not None:
                    intelligence_text.append(f"PE(TTM)={f_info['pe']:.2f}")
                if f_info.get("pb"):
                    intelligence_text.append(f"PB={f_info['pb']:.2f}")
                if f_info.get("float_mv"):
                    intelligence_text.append(f"流通市值={f_info['float_mv']/1e8:.1f}亿")
                if f_flow.get("today_net") is not None:
                    intelligence_text.append(f"今日主力净流入={f_flow['today_net']/1e8:+.2f}亿")
                if f_flow.get("turnover_rate"):
                    intelligence_text.append(f"换手率={f_flow['turnover_rate']:.1f}%")
                lhb_list = fund_block.get("lhb") or []
                if lhb_list:
                    intelligence_text.append(f"龙虎榜: {len(lhb_list)} 次上榜")

                # 行业景气度
                industries = fundamental_service.get_hot_industries(top_n=10)
                hot_inds_text = "Top10 热门行业: " + " / ".join(
                    f"{i['name']}({i['change_pct']:+.2f}%)" for i in industries[:10]
                ) if industries else ""

                # 命中策略
                strategies_text = "命中策略: " + " / ".join(
                    s['name'] for s in r.get('strategies', [])
                ) if r.get('strategies') else "未命中经典策略"

                preloaded = [
                    ToolResult(call_id=None, name="get_realtime_quote", output=quote_data),
                    ToolResult(call_id=None, name="get_daily_bars", output={"bars": bars[-30:] if bars else []}),
                    ToolResult(call_id=None, name="get_technical_features", output=feat),
                    ToolResult(call_id=None, name="detect_chart_pattern", output=pattern_data),
                    ToolResult(call_id=None, name="get_support_resistance", output={
                        "support_levels": [ind.get("low_20"), ind.get("low_60")],
                        "resistance_levels": [ind.get("high_20"), ind.get("high_60")],
                    }),
                    # 给 LLM 一个简化的"new"和"sentiment"，里面塞基本面+行业景气
                    ToolResult(call_id=None, name="search_news", output={
                        "news": [{
                            "title": "扫描器整合数据（基本面+资金面）",
                            "content": " | ".join(intelligence_text),
                            "publish_time": "today",
                        }, {
                            "title": "行业景气度",
                            "content": hot_inds_text,
                            "publish_time": "today",
                        }, {
                            "title": "技术形态命中",
                            "content": strategies_text,
                            "publish_time": "today",
                        }],
                    }),
                    ToolResult(call_id=None, name="analyze_news_sentiment", output={
                        "avg_sentiment": 0.1 if (f_flow.get("today_net") or 0) > 0 else -0.1,
                        "sentiment_label": "中性偏正" if (f_flow.get("today_net") or 0) > 0 else "中性",
                        "negative_events_count": 0,
                    }),
                ]

                agent = SuperAnalystAgent()
                run = agent.run(
                    f"深度分析 {r['symbol']} {r.get('name', '')}",
                    context={
                        "symbol": r["symbol"],
                        "preloaded_observations": preloaded,
                    },
                )
                ai = run.final_answer or {}

                action = (ai.get("action") or "").upper()
                confidence = int(ai.get("confidence") or 0)
                # 区分：LLM 真正运行 vs 规则引擎兜底
                used_llm = ai.get("llm_powered") is True or ai.get("method") != "fallback_rule_engine"

                r3 = dict(r)
                r3["ai_analysis"] = {
                    "action": action,
                    "confidence": confidence,
                    "used_llm": used_llm,  # False = LLM 失败/未配置，是规则引擎兜底
                    "method": ai.get("method", "llm"),
                    "risk_level": ai.get("risk_level"),
                    "time_horizon": ai.get("time_horizon"),
                    "core_conclusion": ai.get("core_conclusion", {}),
                    "summary": ai.get("summary", "")[:400],
                    "key_points": ai.get("key_points", [])[:5],
                    "catalysts": ai.get("catalysts", [])[:3],
                    "risk_factors": ai.get("risk_factors", [])[:3],
                    "buy_price_low": ai.get("buy_price_low"),
                    "buy_price_high": ai.get("buy_price_high"),
                    "stop_loss": ai.get("stop_loss"),
                    "take_profit": ai.get("take_profit"),
                    "rejected_reason": None,
                }

                # AI 立场不达标：标记为 rejected 但保留信息
                if action not in ("BUY", "HOLD") or confidence < 55:
                    r3["ai_analysis"]["rejected_reason"] = f"AI 评级 {action} / 把握度 {confidence}%（不推荐）"
                    r3["_ai_rejected"] = True
                    log.info("T3 AI 不推荐 %s: action=%s conf=%d", r["symbol"], action, confidence)

                return r3
            except Exception as e:
                log.warning("T3 LLM %s failed: %s", r.get("symbol"), e)
                r3 = dict(r)
                r3["ai_analysis"] = {"error": str(e)[:200]}
                return r3

        # 并行调用 LLM（限制并发避免触发限流）
        final_results = []
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="scanner-t3") as ex:
            futures = {ex.submit(_llm_one, r): r for r in llm_candidates}
            for fut in as_completed(futures):
                try:
                    r = fut.result(timeout=180)  # 3 分钟单股超时
                    if r:
                        final_results.append(r)
                        if progress_callback:
                            progress_callback("tier3_progress", {
                                "completed": len(final_results),
                                "total": len(llm_candidates),
                                "symbol": r["symbol"],
                            })
                except Exception:
                    pass

        # 排序：BUY > HOLD > 其他；同档内按 confidence + 综合分
        def _sort_key(r):
            ai = r.get("ai_analysis") or {}
            action = ai.get("action") or ""
            conf = ai.get("confidence") or 0
            tech = r.get("score", 0)
            quality = (r.get("fundamental") or {}).get("quality", 0)
            flow = (r.get("fundamental") or {}).get("flow_score", 0)
            # 综合分（用于同档排序）：技术 + 基本面 + 资金面 + AI 置信度
            composite = tech * 0.4 + quality * 1.2 + flow * 1.2 + conf * 0.4
            # 三档：1 = BUY, 2 = HOLD, 3 = 其他
            tier = 1 if action == "BUY" else (2 if action == "HOLD" else 3)
            # rejected 一律降到第 4 档
            if r.get("_ai_rejected"):
                tier = 4
            return (tier, -composite)

        final_results.sort(key=_sort_key)
        # 把 rejected 和正常分开计数
        recommended = [r for r in final_results if not r.get("_ai_rejected")]
        rejected = [r for r in final_results if r.get("_ai_rejected")]
        log.info("scanner T3 完成：LLM 复审 %d → AI 推荐 %d，AI 否决 %d",
                 len(llm_candidates), len(recommended), len(rejected))
        if progress_callback:
            progress_callback("tier3_done", {
                "count": len(recommended),
                "rejected": len(rejected),
            })

    # 推荐列表：未被 AI 否决的；保留 rejected 列表给前端显示
    recommended_list = [r for r in final_results if not r.get("_ai_rejected")][:top_n]
    rejected_list = [r for r in final_results if r.get("_ai_rejected")]
    final_results = recommended_list

    elapsed = round((time.monotonic() - t0) * 1000, 1)
    log.info("scanner: 三层漏斗完成，AI 推荐 %d / AI 否决 %d，耗时 %.0fms",
             len(final_results), len(rejected_list) if enable_llm else 0, elapsed)

    # 同时输出大盘行业排行（前端可用于显示）
    hot_inds = fundamental_service.get_hot_industries(top_n=10)

    # 检测 LLM 实际运行状态（盘点 Tier-3 中实际有多少只用了真 LLM）
    llm_status = "disabled"
    if enable_llm:
        all_t3 = final_results + rejected_list
        llm_used = [r for r in all_t3 if (r.get("ai_analysis") or {}).get("used_llm")]
        rule_used = [r for r in all_t3 if (r.get("ai_analysis") or {}).get("used_llm") is False]
        if rule_used and not llm_used:
            llm_status = "all_failed"  # LLM 全失败（如余额不足）
        elif rule_used:
            llm_status = "partial"  # 部分失败
        else:
            llm_status = "ok"

    output = {
        "scanned": len(all_quotes),
        "candidates": len(candidates),
        "analyzed": len(pool),
        "tier1_count": len(tier1_top),
        "tier2_count": len(tier2_results) if enable_fundamental else None,
        "tier3_count": (len(final_results) + len(rejected_list)) if enable_llm else None,
        "results": final_results,
        "rejected_results": rejected_list if enable_llm else [],
        "market_status": market_status,
        "hot_industries": hot_inds,
        "llm_status": llm_status,
        "elapsed_ms": elapsed,
        "cached": False,
        "params": {
            "top_n": top_n,
            "min_score": min_score,
            "candidate_pool": candidate_pool,
            "required_strategies": required_strategies,
            "enable_fundamental": enable_fundamental,
            "enable_llm": enable_llm,
            "llm_top_n": llm_top_n,
        },
    }

    _scan_cache[cache_key] = output
    _scan_ts = time.monotonic()
    return output


def _compute_market_status(all_quotes: list[dict]) -> dict:
    total = len(all_quotes)
    if total == 0:
        return {}

    up = sum(1 for q in all_quotes if q.get("change_pct", 0) > 0)
    down = sum(1 for q in all_quotes if q.get("change_pct", 0) < 0)
    flat = total - up - down
    # 涨跌停按各自板块的限制（创业板/科创板20%，北交所30%，主板10%，ST 5%）
    def _is_limit_up(q):
        lp = q.get("limit_pct", 0.10)
        return q.get("change_pct", 0) >= lp * 100 - 0.1
    def _is_limit_down(q):
        lp = q.get("limit_pct", 0.10)
        return q.get("change_pct", 0) <= -(lp * 100 - 0.1)
    limit_up = sum(1 for q in all_quotes if _is_limit_up(q))
    limit_down = sum(1 for q in all_quotes if _is_limit_down(q))

    indices = market_service.get_realtime_quotes(["000001.SH", "399001.SZ", "399006.SZ"])
    name_map = {"000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指"}
    indices_data = [
        {
            "name": name_map.get(q["symbol"], q["symbol"]),
            "symbol": q["symbol"],
            "price": q["price"],
            "change_pct": q["change_pct"],
        }
        for q in indices
    ]

    up_ratio = up / total if total else 0.5
    if up_ratio > 0.65:
        sentiment = "强势"
    elif up_ratio > 0.55:
        sentiment = "偏强"
    elif up_ratio > 0.45:
        sentiment = "中性"
    elif up_ratio > 0.35:
        sentiment = "偏弱"
    else:
        sentiment = "弱势"

    return {
        "total": total, "up": up, "down": down, "flat": flat,
        "limit_up": limit_up, "limit_down": limit_down,
        "up_ratio": round(up_ratio * 100, 1),
        "sentiment": sentiment,
        "indices": indices_data,
    }


def get_strategy_list() -> list[dict]:
    """返回所有可用策略列表"""
    return [
        {"name": "放量上涨", "desc": "涨幅<9.5%且收>开 + 成交额≥2亿 + 量比≥2", "category": "短线突破"},
        {"name": "均线多头", "desc": "MA30持续向上 + 30日内涨幅≥20%", "category": "中长线趋势"},
        {"name": "停机坪", "desc": "近15日有放量大涨，之后小阳整理", "category": "强势整理"},
        {"name": "回踩年线", "desc": "突破MA250后回踩，缩量企稳", "category": "中长线趋势"},
        {"name": "突破平台", "desc": "60日内突破MA60 + 放量", "category": "中线突破"},
        {"name": "海龟交易", "desc": "突破60日最高收盘价", "category": "趋势跟踪"},
        {"name": "高而窄旗形", "desc": "10-24日内连续两涨停 + 当前在高位", "category": "强势股"},
        {"name": "低ATR成长", "desc": "10日波幅≥10%（温和上涨）", "category": "稳健成长"},
        {"name": "四线多头", "desc": "MA5>MA10>MA20>MA60", "category": "中长线趋势"},
        {"name": "超跌反弹", "desc": "RSI从超卖区(<30)回升至35-60", "category": "反转抄底"},
        {"name": "双底突破", "desc": "30日内W底形态突破颈线", "category": "底部反转"},
    ]


def clear_cache():
    global _scan_cache, _scan_ts, _kline_cache
    _scan_cache = {}
    _scan_ts = 0.0
    _kline_cache = {}
