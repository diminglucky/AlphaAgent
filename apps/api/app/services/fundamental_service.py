"""基本面 + 资金面 服务

提供：
- 基本面：流通市值、PE、PB、所属行业、上市时间、是否 ST
- 资金面：主力资金净流入（5 日）、龙虎榜
- 北向：通过 AKShare 沪深港通持股数据

设计原则：
1. 所有外部接口都加 try/except + 缓存（避免反复打到 AKShare）
2. 缓存 TTL 6 小时（基本面变化慢）
3. 龙虎榜全市场每天拉一次，缓存到内存里
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

log = logging.getLogger("quant.fundamental")

# 单股基本面缓存（TTL 6 小时）
_info_cache: dict[str, tuple[float, dict]] = {}
_INFO_TTL = 6 * 3600

# 龙虎榜全市场缓存（每天刷新一次）
_lhb_cache: dict[str, list[dict]] = {}  # symbol -> 上榜记录
_lhb_ts: float = 0.0
_lhb_lock = threading.Lock()
_LHB_TTL = 24 * 3600

# 资金流缓存（TTL 1 小时，每天盘后更新）
_flow_cache: dict[str, tuple[float, dict]] = {}
_FLOW_TTL = 3600

# 全市场资金流缓存（一次拉全部，避免逐股调用）
_market_flow_cache: dict[str, dict] = {}  # code -> {today_net, today_inflow, today_outflow, turnover_rate}
_market_flow_ts: float = 0.0
_market_flow_lock = threading.Lock()
_MARKET_FLOW_TTL = 3600  # 1 hour


def _ak():
    import akshare as ak
    return ak


def _safe_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        return None if f != f else f  # 排除 NaN
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 基本面：流通市值 / PE / PB / 行业 / 上市时间
# ---------------------------------------------------------------------------

def get_stock_info(symbol: str) -> dict:
    """获取单股基本面信息（用 stock_value_em，稳定且快）。

    Returns dict with keys:
      - name, industry, total_mv, float_mv, list_date, days_listed, is_st
      - pe (TTM), pe_static, pb, peg, ps
    缓存 6 小时。
    """
    code = symbol.split(".")[0]
    cached = _info_cache.get(code)
    if cached and (time.monotonic() - cached[0]) < _INFO_TTL:
        return cached[1]

    info = {
        "symbol": symbol,
        "code": code,
        "name": "",
        "industry": "",
        "total_mv": None,
        "float_mv": None,
        "list_date": "",
        "days_listed": None,
        "is_st": False,
        "pe": None,
        "pe_static": None,
        "pb": None,
        "peg": None,
        "ps": None,
        "_partial": True,
    }

    # === 主接口：stock_value_em（含 PE/PB/市值，稳定）===
    try:
        ak = _ak()
        df = ak.stock_value_em(symbol=code)
        if df is not None and not df.empty:
            row = df.tail(1).iloc[0]
            info["pe"] = _safe_float(row.get("PE(TTM)"))
            info["pe_static"] = _safe_float(row.get("PE(静)"))
            info["pb"] = _safe_float(row.get("市净率"))
            info["peg"] = _safe_float(row.get("PEG值"))
            info["ps"] = _safe_float(row.get("市销率"))
            info["total_mv"] = _safe_float(row.get("总市值"))
            info["float_mv"] = _safe_float(row.get("流通市值"))
            info["_partial"] = False
    except Exception as e:
        log.debug("stock_value_em(%s) failed: %s", symbol, e)

    # === 辅助：从 quote 拿到股票名称 + ST 标记（不依赖东方财富个股接口）===
    try:
        from apps.api.app.services import market_service
        q = market_service.get_single_quote(symbol)
        if q:
            info["name"] = q.get("name", "")
            info["is_st"] = "ST" in info["name"] or "*ST" in info["name"]
    except Exception:
        pass

    _info_cache[code] = (time.monotonic(), info)
    return info


# ---------------------------------------------------------------------------
# 资金面：主力净流入
# ---------------------------------------------------------------------------

def _parse_amt(s) -> Optional[float]:
    """同花顺资金流字段解析：'5.87亿' / '6043.55万' → 元（float）"""
    if s is None:
        return None
    txt = str(s).strip().replace(",", "")
    if not txt or txt == "-":
        return None
    try:
        sign = -1 if txt.startswith("-") else 1
        txt = txt.lstrip("-+")
        if "亿" in txt:
            return sign * float(txt.replace("亿", "")) * 1e8
        if "万" in txt:
            return sign * float(txt.replace("万", "")) * 1e4
        return sign * float(txt)
    except Exception:
        return None


def _ensure_market_flow():
    """一次性拉取全市场资金流，缓存 1 小时"""
    global _market_flow_cache, _market_flow_ts
    with _market_flow_lock:
        if _market_flow_cache and (time.monotonic() - _market_flow_ts) < _MARKET_FLOW_TTL:
            return
        try:
            ak = _ak()
            df = ak.stock_fund_flow_individual()
            if df is None or df.empty:
                return
            cache = {}
            for _, row in df.iterrows():
                code = str(row.get("股票代码", "")).strip().zfill(6)
                if not code:
                    continue
                cache[code] = {
                    "name": str(row.get("股票简称", "")),
                    "today_net": _parse_amt(row.get("净额")),
                    "today_inflow": _parse_amt(row.get("流入资金")),
                    "today_outflow": _parse_amt(row.get("流出资金")),
                    "today_turnover": _parse_amt(row.get("成交额")),
                    "today_pct": _safe_float(str(row.get("涨跌幅") or "0").replace("%", "")),
                    "turnover_rate": _safe_float(str(row.get("换手率") or "0").replace("%", "")),
                }
            _market_flow_cache = cache
            _market_flow_ts = time.monotonic()
            log.info("market fund_flow refreshed: %d stocks", len(cache))
        except Exception as e:
            log.warning("ensure_market_flow failed: %s", e)


def get_fund_flow(symbol: str) -> dict:
    """获取个股当日主力资金流（从全市场缓存读取）。"""
    code = symbol.split(".")[0].zfill(6)
    cached = _flow_cache.get(code)
    if cached and (time.monotonic() - cached[0]) < _FLOW_TTL:
        return cached[1]

    out = {
        "today_net": None,           # 当日净额（流入-流出）
        "today_inflow": None,
        "today_outflow": None,
        "today_pct": None,
        "turnover_rate": None,
        "_partial": True,
    }

    _ensure_market_flow()
    rec = _market_flow_cache.get(code)
    if rec:
        out.update({
            "today_net": rec.get("today_net"),
            "today_inflow": rec.get("today_inflow"),
            "today_outflow": rec.get("today_outflow"),
            "today_pct": rec.get("today_pct"),
            "turnover_rate": rec.get("turnover_rate"),
            "_partial": False,
        })

    _flow_cache[code] = (time.monotonic(), out)
    return out


# ---------------------------------------------------------------------------
# 龙虎榜：每天全市场拉一次
# ---------------------------------------------------------------------------

def _fetch_lhb_today():
    """从 AKShare 拉近 5 日龙虎榜（东方财富，可能不可达，失败返回空 dict）。"""
    try:
        ak = _ak()
        from datetime import timedelta
        today = datetime.now()
        start = (today - timedelta(days=5)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        # 添加请求超时保护：如果东方财富不可达，避免阻塞太久
        df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        if df is None or df.empty:
            return {}

        result: dict[str, list[dict]] = {}
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            if not code:
                continue
            entry = {
                "date": str(row.get("上榜日", "")),
                "reason": str(row.get("上榜原因", "")),
                "net_buy": float(row.get("龙虎榜净买额") or 0),
                "interpret": str(row.get("解读", "")),
                "next_1d": _safe_float(row.get("上榜后1日")),
                "next_5d": _safe_float(row.get("上榜后5日")),
            }
            result.setdefault(code, []).append(entry)
        log.info("龙虎榜数据加载成功: %d 只股票", len(result))
        return result
    except Exception as e:
        log.warning("龙虎榜拉取失败（已跳过）: %s", str(e)[:100])
        return {}


def get_lhb_record(symbol: str) -> list[dict]:
    """获取个股近 5 日的龙虎榜记录。"""
    global _lhb_cache, _lhb_ts
    with _lhb_lock:
        if not _lhb_cache or (time.monotonic() - _lhb_ts) > _LHB_TTL:
            _lhb_cache = _fetch_lhb_today()
            _lhb_ts = time.monotonic()
    code = symbol.split(".")[0]
    return _lhb_cache.get(code, [])


# ---------------------------------------------------------------------------
# 基本面综合评估：质量过滤 + 加分扣分
# ---------------------------------------------------------------------------

def evaluate_fundamental(symbol: str, name: str = "") -> dict:
    """对单股做基本面 + 资金面综合评估，返回：
      - hard_blocks: 一票否决的原因列表（非空时直接淘汰）
      - bonus: 加分项（list of (desc, score)）
      - penalty: 扣分项（list of (desc, score)）
      - net_score: 综合调整分（-30 ~ +30）
      - info: 基本面 dict
      - flow: 资金面 dict
      - lhb: 龙虎榜 list
    """
    info = get_stock_info(symbol)
    if not info["name"] and name:
        info["name"] = name
    if name and ("ST" in name or "*ST" in name):
        info["is_st"] = True

    flow = get_fund_flow(symbol)
    lhb = get_lhb_record(symbol)

    blocks: list[str] = []
    bonus: list[tuple[str, int]] = []
    penalty: list[tuple[str, int]] = []

    # === 一票否决（hard_blocks）===
    if info.get("is_st"):
        blocks.append("ST 风险股，建议规避")

    days_listed = info.get("days_listed")
    if days_listed is not None and days_listed < 60:
        blocks.append(f"上市仅 {days_listed} 天（次新股，价格不稳）")

    float_mv = info.get("float_mv")
    if float_mv is not None and float_mv > 0 and float_mv < 30e8:
        blocks.append(f"流通市值仅 {float_mv/1e8:.1f} 亿（小盘庄股温床）")

    # PE 严重异常一票否决
    pe = info.get("pe")
    if pe is not None:
        if pe < 0 and abs(pe) > 200:
            blocks.append(f"PE={pe:.1f}（深度亏损）")
        elif pe > 200:
            blocks.append(f"PE={pe:.1f}（估值严重过高）")

    # 龙虎榜负面：上榜原因含「跌幅偏离值」+ 净卖出
    for r in lhb:
        if "跌幅" in r["reason"] and r["net_buy"] < -1e7:
            blocks.append(f"龙虎榜：{r['date']} {r['reason']}，机构净卖出 {r['net_buy']/1e8:.2f}亿")
            break

    # === 加分项 ===
    # 中等盘子（30-200 亿流通市值，机构关注且不易被操纵）
    if float_mv is not None:
        if 30e8 <= float_mv <= 200e8:
            bonus.append((f"流通市值 {float_mv/1e8:.0f}亿，盘子适中", 5))
        elif 200e8 < float_mv <= 1000e8:
            bonus.append((f"流通市值 {float_mv/1e8:.0f}亿，机构重仓股", 3))

    # PE 合理估值
    if pe is not None and 0 < pe <= 30:
        bonus.append((f"PE={pe:.1f}，估值合理", 4))
    elif pe is not None and 30 < pe <= 60:
        bonus.append((f"PE={pe:.1f}，估值偏高但可接受", 1))

    # 资金面：当日主力净流入
    today_net = flow.get("today_net")
    if today_net is not None:
        if today_net > 1e8:
            bonus.append((f"今日主力净流入 {today_net/1e8:.2f}亿，资金强势", 8))
        elif today_net > 0.3e8:
            bonus.append((f"今日主力净流入 {today_net/1e8:.2f}亿", 4))

    # 换手率合理（活跃但不过热）
    tor = flow.get("turnover_rate")
    if tor is not None and 2 <= tor <= 8:
        bonus.append((f"换手率 {tor:.1f}%（活跃度健康）", 3))

    # 龙虎榜机构净买入
    for r in lhb:
        if r["net_buy"] > 5e7 and "机构" in r["interpret"]:
            bonus.append((f"龙虎榜：{r['date']} 机构净买入 {r['net_buy']/1e8:.2f}亿", 8))
            break

    # === 扣分项 ===
    if pe is not None:
        if 100 < pe <= 200:
            penalty.append((f"PE={pe:.1f}，估值偏高", -6))
        elif pe < 0:
            penalty.append((f"PE={pe:.1f}（亏损）", -8))

    if float_mv is not None and float_mv > 1000e8:
        penalty.append((f"市值 {float_mv/1e8:.0f}亿，盘子过大涨速慢", -3))

    if today_net is not None and today_net < -0.5e8:
        penalty.append((f"今日主力净流出 {abs(today_net)/1e8:.2f}亿", -8))

    if tor is not None:
        if tor > 20:
            penalty.append((f"换手率 {tor:.1f}%（过热）", -5))
        elif tor < 0.5:
            penalty.append((f"换手率仅 {tor:.1f}%（流动性差）", -3))

    net_score = sum(s for _, s in bonus) + sum(s for _, s in penalty)

    return {
        "hard_blocks": blocks,
        "bonus": [{"desc": d, "score": s} for d, s in bonus],
        "penalty": [{"desc": d, "score": s} for d, s in penalty],
        "net_score": net_score,
        "info": info,
        "flow": flow,
        "lhb": lhb,
    }


def clear_cache():
    """清除所有缓存"""
    global _info_cache, _flow_cache, _lhb_cache, _lhb_ts, _market_flow_cache, _market_flow_ts
    _info_cache.clear()
    _flow_cache.clear()
    _market_flow_cache = {}
    _market_flow_ts = 0.0
    _lhb_cache = {}
    _lhb_ts = 0.0
