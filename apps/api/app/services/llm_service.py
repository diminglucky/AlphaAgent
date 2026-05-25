"""LLM 服务 — 专业金融分析师 Agent"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Optional

import httpx

from apps.api.app.core.config import get_settings

log = logging.getLogger("quant.llm")


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

def _get_llm_settings() -> dict:
    """获取 LLM 配置：运行时覆盖 > 环境变量"""
    from libs.llm_analyst.runtime_config import get_override
    ov = get_override()
    settings = get_settings()
    return {
        "api_key":     ov.get("api_key")    or settings.llm_api_key,
        "base_url":    ov.get("base_url")   or settings.llm_base_url,
        "model":       ov.get("model")      or settings.llm_model,
        "temperature": ov.get("temperature") if ov.get("temperature") is not None else settings.llm_temperature,
        "timeout":     ov.get("timeout")    or settings.llm_timeout,
    }


def _chat(messages: list[dict], json_mode: bool = False, max_tokens: int = 4000) -> str:
    cfg = _get_llm_settings()
    if not cfg["api_key"]:
        return ""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    }
    payload: dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg["temperature"],
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        resp = httpx.post(
            cfg["base_url"].rstrip("/") + "/chat/completions",
            headers=headers,
            json=payload,
            timeout=cfg["timeout"],
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning("LLM call failed: %s", e)
        return ""


# ---------------------------------------------------------------------------
# 技术指标计算
# ---------------------------------------------------------------------------

def _calc_indicators(kline: list[dict]) -> dict:
    """计算完整技术指标"""
    if not kline:
        return {}

    closes = [float(b.get("close", 0)) for b in kline]
    highs  = [float(b.get("high", 0)) for b in kline]
    lows   = [float(b.get("low", 0)) for b in kline]
    vols   = [float(b.get("amount", b.get("volume", 0))) for b in kline]
    n = len(closes)

    def ma(prices, period):
        if len(prices) < period:
            return None
        return round(sum(prices[-period:]) / period, 3)

    def ema(prices, period):
        if len(prices) < period:
            return None
        k = 2 / (period + 1)
        e = prices[0]
        for p in prices[1:]:
            e = p * k + e * (1 - k)
        return round(e, 3)

    def rsi(prices, period=14):
        if len(prices) < period + 1:
            return None
        gains, losses = [], []
        for i in range(1, len(prices)):
            d = prices[i] - prices[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - 100 / (1 + rs), 2)

    def ema_series(prices, period):
        if not prices:
            return []
        k = 2 / (period + 1)
        out = [prices[0]]
        for p in prices[1:]:
            out.append(p * k + out[-1] * (1 - k))
        return out

    def macd(prices):
        if len(prices) < 26:
            return None, None, None
        ema12_series = ema_series(prices, 12)
        ema26_series = ema_series(prices, 26)
        dif_series = [fast - slow for fast, slow in zip(ema12_series, ema26_series)]
        dea_series = ema_series(dif_series, 9)
        dif = round(dif_series[-1], 4)
        dea = round(dea_series[-1], 4)
        hist = round((dif - dea) * 2, 4)
        return dif, dea, hist

    def bollinger(prices, period=20):
        if len(prices) < period:
            return None, None, None
        mid = sum(prices[-period:]) / period
        std = math.sqrt(sum((p - mid) ** 2 for p in prices[-period:]) / period)
        return round(mid - 2*std, 3), round(mid, 3), round(mid + 2*std, 3)

    def kdj(highs, lows, closes, period=9):
        if len(closes) < period:
            return None, None, None
        h9 = max(highs[-period:])
        l9 = min(lows[-period:])
        if h9 == l9:
            return 50.0, 50.0, 50.0
        rsv = (closes[-1] - l9) / (h9 - l9) * 100
        k = round(rsv * 1/3 + 50 * 2/3, 2)
        d = round(k * 1/3 + 50 * 2/3, 2)
        j = round(3*k - 2*d, 2)
        return k, d, j

    # 涨跌幅
    ret_1d  = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if n >= 2 else 0
    ret_5d  = round((closes[-1] - closes[-5]) / closes[-5] * 100, 2) if n >= 5 else 0
    ret_10d = round((closes[-1] - closes[-10]) / closes[-10] * 100, 2) if n >= 10 else 0
    ret_20d = round((closes[-1] - closes[-20]) / closes[-20] * 100, 2) if n >= 20 else 0
    ret_60d = round((closes[-1] - closes[-60]) / closes[-60] * 100, 2) if n >= 60 else 0

    # 波动率
    if n >= 20:
        daily_rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(max(1, n-20), n)]
        avg_ret = sum(daily_rets) / len(daily_rets)
        vol_20d = round(math.sqrt(sum((r - avg_ret)**2 for r in daily_rets) / len(daily_rets)) * 100, 3)
    else:
        vol_20d = None

    # 成交量分析
    vol_ma5  = sum(vols[-5:]) / 5 if n >= 5 else None
    vol_ma20 = sum(vols[-20:]) / 20 if n >= 20 else None
    vol_ratio = round(vols[-1] / vol_ma20, 2) if vol_ma20 and vol_ma20 > 0 else None

    # 支撑/压力位
    high_20 = max(highs[-20:]) if n >= 20 else max(highs)
    low_20  = min(lows[-20:]) if n >= 20 else min(lows)
    high_60 = max(highs[-60:]) if n >= 60 else max(highs)
    low_60  = min(lows[-60:]) if n >= 60 else min(lows)

    dif, dea, hist = macd(closes)
    bb_lower, bb_mid, bb_upper = bollinger(closes)
    k_val, d_val, j_val = kdj(highs, lows, closes)

    return {
        "ma5":  ma(closes, 5),
        "ma10": ma(closes, 10),
        "ma20": ma(closes, 20),
        "ma60": ma(closes, 60),
        "ema12": ema(closes, 12),
        "ema26": ema(closes, 26),
        "rsi14": rsi(closes, 14),
        "macd_dif": dif,
        "macd_dea": dea,
        "macd_hist": hist,
        "bb_lower": bb_lower,
        "bb_mid": bb_mid,
        "bb_upper": bb_upper,
        "kdj_k": k_val,
        "kdj_d": d_val,
        "kdj_j": j_val,
        "ret_1d": ret_1d,
        "ret_5d": ret_5d,
        "ret_10d": ret_10d,
        "ret_20d": ret_20d,
        "ret_60d": ret_60d,
        "vol_20d": vol_20d,
        "vol_ratio": vol_ratio,
        "high_20": round(high_20, 3),
        "low_20": round(low_20, 3),
        "high_60": round(high_60, 3),
        "low_60": round(low_60, 3),
        "current": round(closes[-1], 3),
        "pos_in_20d": round((closes[-1] - low_20) / (high_20 - low_20) * 100, 1) if high_20 != low_20 else 50,
        "pos_in_60d": round((closes[-1] - low_60) / (high_60 - low_60) * 100, 1) if high_60 != low_60 else 50,
    }


def _get_market_context() -> str:
    """获取大盘指数数据作为市场背景"""
    try:
        from apps.api.app.services.market_service import get_realtime_quotes
        # 上证指数、深证成指、创业板指
        indices = get_realtime_quotes(["000001.SH", "399001.SZ", "399006.SZ"])
        if not indices:
            return "大盘数据暂不可用"
        lines = []
        name_map = {"000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指"}
        for q in indices:
            n = name_map.get(q["symbol"], q["symbol"])
            lines.append(f"{n}: {q['price']:.2f}（{'+' if q['change_pct']>=0 else ''}{q['change_pct']:.2f}%）")
        return "、".join(lines)
    except Exception:
        return "大盘数据暂不可用"


# ---------------------------------------------------------------------------
# 主分析函数
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一位拥有20年经验的顶级A股投资分析师，曾任职于头部券商研究所，精通：
- 技术分析：K线形态、均线系统、MACD/KDJ/RSI/布林带等指标
- 基本面分析：估值体系、行业景气度、公司竞争力
- 市场情绪：资金流向、主力行为、板块轮动
- 宏观研判：政策影响、经济周期、市场风格

你的分析风格：
1. 数据驱动，每个结论都有具体数据支撑
2. 多维度交叉验证，不依赖单一指标
3. 明确指出风险，不夸大收益
4. 给出具体可操作的价格区间，而非模糊建议
5. 用专业但易懂的中文表达

你必须严格按照指定的 JSON 格式输出，不添加任何额外文字。"""


def analyze_stock(
    symbol: str,
    name: str,
    quote: dict,
    kline: list[dict],
    news: list[dict],
    market_context: Optional[str] = None,
) -> dict:
    """
    专业金融分析师深度分析，返回结构化报告：
    {
        "action": "BUY"|"SELL"|"HOLD"|"WATCH",
        "confidence": 0-100,
        "buy_price_low": float,
        "buy_price_high": float,
        "stop_loss": float,
        "take_profit": float,
        "risk_level": "低"|"中"|"高",
        "time_horizon": "短线(1-5日)"|"中线(1-4周)"|"长线(1-3月)",

        # 详细分析
        "summary": str,           # 200字综合结论
        "technical_analysis": str, # 技术面详细分析
        "news_analysis": str,      # 新闻/消息面分析
        "market_analysis": str,    # 大盘/市场环境分析
        "risk_analysis": str,      # 风险提示

        "key_points": [str],       # 5个核心要点
        "catalysts": [str],        # 潜在催化剂
        "risk_factors": [str],     # 主要风险因素

        "support_levels": [float], # 支撑位
        "resistance_levels": [float], # 压力位

        "llm_powered": bool,
    }
    """
    settings = get_settings()
    if not settings.llm_api_key:
        return _fallback_analysis(symbol, name, quote, kline)

    price = quote.get("price", 0)
    ind = _calc_indicators(kline)
    mkt = market_context or _get_market_context()

    # 构建K线趋势描述
    trend_desc = _describe_trend(ind, price)

    # 新闻摘要
    news_text = "\n".join(
        f"  [{n.get('time','')[:16]}] {n.get('title','')}（来源：{n.get('source','')}）"
        for n in news[:8]
    ) if news else "  暂无近期相关新闻"

    # 近期K线数据（最近10根）
    recent_kline = ""
    if kline:
        for b in kline[-10:]:
            chg = b.get("change_pct", 0)
            recent_kline += f"  {b['date']}: 开{b['open']:.2f} 高{b['high']:.2f} 低{b['low']:.2f} 收{b['close']:.2f} 涨跌{chg:+.2f}%\n"

    user_prompt = f"""请对以下A股进行深度专业分析：

═══════════════════════════════════════
【基本信息】
股票：{name}（{symbol}）
当前价格：¥{price:.2f}
今日涨跌：{quote.get('change_pct', 0):+.2f}%（{quote.get('change', 0):+.2f}元）
今开：{quote.get('open', 0):.2f}  最高：{quote.get('high', 0):.2f}  最低：{quote.get('low', 0):.2f}
成交额：{quote.get('turnover', 0)/1e8:.2f}亿元
PE（动态）：{quote.get('pe_ratio', 0):.1f}倍  PB：{quote.get('pb_ratio', 0):.2f}倍

═══════════════════════════════════════
【大盘环境】
{mkt}

═══════════════════════════════════════
【技术指标】
均线系统：
  MA5={ind.get('ma5','N/A')}  MA10={ind.get('ma10','N/A')}  MA20={ind.get('ma20','N/A')}  MA60={ind.get('ma60','N/A')}
  EMA12={ind.get('ema12','N/A')}  EMA26={ind.get('ema26','N/A')}

动量指标：
  RSI(14)={ind.get('rsi14','N/A')}
  MACD: DIF={ind.get('macd_dif','N/A')}  DEA={ind.get('macd_dea','N/A')}  柱={ind.get('macd_hist','N/A')}
  KDJ: K={ind.get('kdj_k','N/A')}  D={ind.get('kdj_d','N/A')}  J={ind.get('kdj_j','N/A')}

布林带：
  下轨={ind.get('bb_lower','N/A')}  中轨={ind.get('bb_mid','N/A')}  上轨={ind.get('bb_upper','N/A')}

价格位置：
  20日区间：{ind.get('low_20','N/A')} ~ {ind.get('high_20','N/A')}（当前在{ind.get('pos_in_20d','N/A')}%位置）
  60日区间：{ind.get('low_60','N/A')} ~ {ind.get('high_60','N/A')}（当前在{ind.get('pos_in_60d','N/A')}%位置）

涨跌幅：
  1日：{ind.get('ret_1d',0):+.2f}%  5日：{ind.get('ret_5d',0):+.2f}%  10日：{ind.get('ret_10d',0):+.2f}%
  20日：{ind.get('ret_20d',0):+.2f}%  60日：{ind.get('ret_60d',0):+.2f}%

波动率（20日）：{ind.get('vol_20d','N/A')}%/日
成交量比（今日/20日均）：{ind.get('vol_ratio','N/A')}x

趋势判断：{trend_desc}

═══════════════════════════════════════
【近10日K线】
{recent_kline}
═══════════════════════════════════════
【近期新闻消息】
{news_text}

═══════════════════════════════════════

请基于以上全部数据，以顶级卖方分析师的专业水准，输出以下JSON格式的深度分析报告：

{{
  "action": "BUY或SELL或HOLD或WATCH",
  "confidence": 0到100的整数（基于综合判断的确信度）,
  "buy_price_low": 建议买入价下限（具体数字，基于支撑位和技术分析）,
  "buy_price_high": 建议买入价上限（具体数字）,
  "stop_loss": 止损价（具体数字，跌破此价位应止损）,
  "take_profit": 止盈目标价（具体数字，基于压力位和目标涨幅）,
  "risk_level": "低或中或高",
  "time_horizon": "短线(1-5日)或中线(1-4周)或长线(1-3月)",

  "summary": "200字以内的综合结论，包含核心逻辑和操作建议",

  "technical_analysis": "详细技术面分析，至少150字：分析均线排列、MACD信号、KDJ状态、布林带位置、成交量配合情况、关键支撑压力位，判断当前趋势强弱",

  "news_analysis": "详细消息面分析，至少100字：分析近期新闻对股价的影响，判断利好/利空性质，评估市场情绪",

  "market_analysis": "大盘环境分析，至少80字：分析当前大盘趋势对该股的影响，判断市场风格是否有利",

  "risk_analysis": "风险提示，至少80字：列举主要风险因素，包括技术面风险、基本面风险、市场风险",

  "key_points": ["核心要点1（具体数据支撑）", "核心要点2", "核心要点3", "核心要点4", "核心要点5"],

  "catalysts": ["潜在催化剂1", "潜在催化剂2", "潜在催化剂3"],

  "risk_factors": ["风险因素1", "风险因素2", "风险因素3"],

  "support_levels": [支撑位1, 支撑位2, 支撑位3],

  "resistance_levels": [压力位1, 压力位2, 压力位3]
}}"""

    raw = _chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        json_mode=True,
        max_tokens=4000,
    )

    if not raw:
        return _fallback_analysis(symbol, name, quote, kline)

    try:
        result = json.loads(raw)
        result["symbol"] = symbol
        result["name"] = name
        result["current_price"] = price
        result["indicators"] = ind
        result["llm_powered"] = True
        return result
    except Exception as e:
        log.warning("LLM parse failed: %s | raw: %s", e, raw[:300])
        return _fallback_analysis(symbol, name, quote, kline)


def _describe_trend(ind: dict, price: float) -> str:
    """根据指标描述趋势"""
    parts = []
    ma5, ma20, ma60 = ind.get("ma5"), ind.get("ma20"), ind.get("ma60")

    if ma5 and ma20 and ma60:
        if price > ma5 > ma20 > ma60:
            parts.append("多头排列（强势上涨）")
        elif price < ma5 < ma20 < ma60:
            parts.append("空头排列（弱势下跌）")
        elif price > ma20:
            parts.append("价格在MA20上方（偏多）")
        else:
            parts.append("价格在MA20下方（偏空）")

    rsi = ind.get("rsi14")
    if rsi:
        if rsi > 70:
            parts.append(f"RSI={rsi}超买区")
        elif rsi < 30:
            parts.append(f"RSI={rsi}超卖区")
        else:
            parts.append(f"RSI={rsi}中性区")

    macd_hist = ind.get("macd_hist")
    if macd_hist is not None:
        parts.append(f"MACD柱{'红柱扩大' if macd_hist > 0 else '绿柱扩大'}")

    return "；".join(parts) if parts else "趋势不明确"


def _fallback_analysis(symbol: str, name: str, quote: dict, kline: list[dict]) -> dict:
    """无 LLM 时的技术分析回退"""
    price = quote.get("price", 0)
    ind = _calc_indicators(kline)

    ma5  = ind.get("ma5", price)
    ma20 = ind.get("ma20", price)
    rsi  = ind.get("rsi14", 50)

    if price > (ma5 or price) > (ma20 or price) and (rsi or 50) < 70:
        action, conf = "WATCH", 55
        reason = f"均线多头排列（MA5={ma5:.2f} > MA20={ma20:.2f}），RSI={rsi:.1f}未超买，趋势向上，可关注买入机会。"
    elif price < (ma5 or price) < (ma20 or price):
        action, conf = "HOLD", 45
        reason = f"均线空头排列（MA5={ma5:.2f} < MA20={ma20:.2f}），趋势偏弱，建议观望。"
    elif rsi and rsi < 30:
        action, conf = "WATCH", 50
        reason = f"RSI={rsi:.1f}进入超卖区，可能存在反弹机会，但需确认企稳信号。"
    else:
        action, conf = "HOLD", 40
        reason = "技术面信号不明确，建议观望等待更清晰的方向。"

    support = round(ind.get("low_20", price * 0.95), 2)
    resist  = round(ind.get("high_20", price * 1.05), 2)

    return {
        "symbol": symbol,
        "name": name,
        "current_price": price,
        "action": action,
        "confidence": conf,
        "buy_price_low": round(support * 1.005, 2),
        "buy_price_high": round(support * 1.02, 2),
        "stop_loss": round(support * 0.97, 2),
        "take_profit": round(resist * 0.98, 2),
        "risk_level": "中",
        "time_horizon": "短线(1-5日)",
        "summary": reason,
        "technical_analysis": f"MA5={ma5:.2f}，MA20={ma20:.2f}，RSI={rsi:.1f}。{reason}",
        "news_analysis": "未配置LLM，无法进行新闻分析。",
        "market_analysis": "未配置LLM，无法进行大盘分析。",
        "risk_analysis": "请配置LLM API Key以获取完整风险分析。",
        "key_points": [
            f"MA5={ma5:.2f}，MA20={ma20:.2f}",
            f"RSI(14)={rsi:.1f}",
            f"20日区间：{ind.get('low_20',0):.2f}~{ind.get('high_20',0):.2f}",
            f"当前位置：20日区间{ind.get('pos_in_20d',50):.0f}%",
            "建议配置LLM获取深度分析",
        ],
        "catalysts": ["配置LLM后可获取催化剂分析"],
        "risk_factors": ["技术面风险", "市场系统性风险", "流动性风险"],
        "support_levels": [support, round(support * 0.97, 2), round(support * 0.94, 2)],
        "resistance_levels": [resist, round(resist * 1.03, 2), round(resist * 1.06, 2)],
        "indicators": ind,
        "llm_powered": False,
    }


def scan_watchlist(watchlist_data: list[dict]) -> list[dict]:
    """扫描自选股，找出最有潜力的机会"""
    mkt = _get_market_context()
    results = []
    for item in watchlist_data:
        try:
            result = analyze_stock(
                symbol=item["symbol"],
                name=item["name"],
                quote=item["quote"],
                kline=item["kline"],
                news=item["news"],
                market_context=mkt,
            )
            results.append(result)
        except Exception as e:
            log.warning("scan %s failed: %s", item.get("symbol"), e)

    action_order = {"BUY": 0, "WATCH": 1, "HOLD": 2, "SELL": 3}
    results.sort(key=lambda x: (action_order.get(x.get("action", "HOLD"), 2), -x.get("confidence", 0)))
    return results
