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
from datetime import date, datetime, timedelta
from typing import Any, Optional

log = logging.getLogger("quant.fundamental")

# 单股基本面缓存（TTL 6 小时）
_info_cache: dict[str, tuple[float, dict]] = {}
_INFO_TTL = 6 * 3600
_MAX_INFO_CACHE = 1000  # 防止内存无限膨胀

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

# 北向持股变化缓存（全市场一次拉取，避免逐股调用东方财富）
_northbound_cache: dict[str, dict] = {}  # code -> 5日北向增减持排行记录
_northbound_ts: float = 0.0
_northbound_lock = threading.Lock()
_NORTHBOUND_TTL = 3600

# 个股研报缓存（接口是逐股查询，只在 Tier-2 候选池调用）
_research_cache: dict[str, tuple[float, dict]] = {}
_RESEARCH_TTL = 24 * 3600
_MAX_RESEARCH_CACHE = 600

# 董监高/相关人员持股变动缓存（全市场一次拉取）
_insider_change_cache: dict[str, dict] = {}
_insider_change_ts: float = 0.0
_insider_change_lock = threading.Lock()
_INSIDER_CHANGE_TTL = 6 * 3600

# 行业热度缓存（每天刷新，盘中按上涨幅度排名）
_hot_industries: list[dict] = []  # [{name, change_pct, net_inflow, leader, leader_pct}]
_hot_concepts: list[dict] = []
_industry_ts: float = 0.0
_industry_lock = threading.Lock()
_INDUSTRY_TTL = 1800  # 30 min


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


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    try:
        if v != v:  # NaN
            return True
    except Exception:
        pass
    txt = str(v).strip()
    return txt in {"", "-", "--", "None", "nan", "NaN"}


def _clean_text(v: Any) -> str:
    return "" if _is_blank(v) else str(v).strip()


def _normalize_code(symbol: str) -> str:
    return symbol.split(".")[0].strip().zfill(6)


def _row_value(row: Any, names: tuple[str, ...], pos: int):
    for name in names:
        try:
            if name in row.index:
                v = row.get(name)
                if not _is_blank(v):
                    return v
        except Exception:
            pass
    try:
        return row.iloc[pos]
    except Exception:
        return None


def _parse_yyyymmdd(v: Any) -> tuple[str, Optional[int]]:
    """Return ISO date + days since list date for AKShare date variants."""
    if _is_blank(v):
        return "", None
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    else:
        txt = str(v).strip()
        if txt.endswith(".0"):
            txt = txt[:-2]
        parsed = None
        for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(txt, fmt).date()
                break
            except Exception:
                continue
        if parsed is None:
            return txt, None
        d = parsed
    return d.isoformat(), max(0, (date.today() - d).days)


def _parse_date_only(v: Any) -> Optional[date]:
    if _is_blank(v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    txt = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(txt[:10] if "-" in txt or "/" in txt else txt, fmt).date()
        except Exception:
            continue
    return None


def _stock_individual_info(code: str) -> dict:
    """Fetch per-stock static facts from Eastmoney via AKShare.

    ``stock_value_em`` is fast for valuation but usually does not include
    industry or list date. This auxiliary call fills those missing facts.
    """
    try:
        ak = _ak()
        df = ak.stock_individual_info_em(symbol=code)
        if df is None or df.empty:
            return {}
        out = {}
        for _, row in df.iterrows():
            key = _clean_text(_row_value(row, ("item", "项目", "指标"), 0))
            if not key:
                continue
            out[key] = _row_value(row, ("value", "值", "数据"), 1)
        return out
    except Exception as e:
        log.debug("stock_individual_info_em(%s) failed: %s", code, e)
        return {}


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
    code = _normalize_code(symbol)
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

    # === 辅助：行业 / 上市时间（用于行业景气度排名和次新股过滤）===
    indiv = _stock_individual_info(code)
    if indiv:
        info["name"] = info["name"] or _clean_text(indiv.get("股票简称") or indiv.get("简称"))
        info["industry"] = _clean_text(indiv.get("行业") or indiv.get("所属行业"))
        list_date, days_listed = _parse_yyyymmdd(indiv.get("上市时间") or indiv.get("上市日期"))
        if list_date:
            info["list_date"] = list_date
            info["days_listed"] = days_listed
        info["total_mv"] = info["total_mv"] or _safe_float(indiv.get("总市值"))
        info["float_mv"] = info["float_mv"] or _safe_float(indiv.get("流通市值"))

    # 容量淘汰：超过上限时删除最早的条目
    if len(_info_cache) >= _MAX_INFO_CACHE:
        oldest_key = min(_info_cache, key=lambda k: _info_cache[k][0])
        _info_cache.pop(oldest_key, None)
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
# 北向资金：沪深港通持股变化
# ---------------------------------------------------------------------------

def _ensure_northbound():
    """Load 5-day northbound holding change rank once per TTL."""
    global _northbound_cache, _northbound_ts
    with _northbound_lock:
        if _northbound_ts > 0 and (time.monotonic() - _northbound_ts) < _NORTHBOUND_TTL:
            return
        try:
            ak = _ak()
            df = ak.stock_hsgt_hold_stock_em(market="北向", indicator="5日排行")
            if df is None or df.empty:
                _northbound_cache = {}
                _northbound_ts = time.monotonic()
                return
            cache = {}
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).strip().zfill(6)
                if not code:
                    continue
                cache[code] = {
                    "name": _clean_text(row.get("名称")),
                    "date": _clean_text(row.get("日期")),
                    "hold_mv": _safe_float(row.get("今日持股-市值")),
                    "hold_ratio_float": _safe_float(row.get("今日持股-占流通股比")),
                    "hold_ratio_total": _safe_float(row.get("今日持股-占总股本比")),
                    "add_shares_5d": _safe_float(row.get("5日增持估计-股数")),
                    "add_mv_5d": _safe_float(row.get("5日增持估计-市值")),
                    "add_mv_pct_5d": _safe_float(row.get("5日增持估计-市值增幅")),
                    "add_ratio_float_5d": _safe_float(row.get("5日增持估计-占流通股比")),
                    "add_ratio_total_5d": _safe_float(row.get("5日增持估计-占总股本比")),
                    "board": _clean_text(row.get("所属板块")),
                }
            _northbound_cache = cache
            _northbound_ts = time.monotonic()
            log.info("northbound holding rank refreshed: %d stocks", len(cache))
        except Exception as e:
            _northbound_ts = time.monotonic()
            log.warning("northbound holding rank failed: %s", str(e)[:100])


def get_northbound_flow(symbol: str) -> dict:
    """Return 5-day northbound holding change for A-share symbols."""
    code = _normalize_code(symbol)
    out = {
        "date": "",
        "hold_mv": None,
        "hold_ratio_float": None,
        "hold_ratio_total": None,
        "add_shares_5d": None,
        "add_mv_5d": None,
        "add_mv_pct_5d": None,
        "add_ratio_float_5d": None,
        "add_ratio_total_5d": None,
        "board": "",
        "_partial": True,
    }
    _ensure_northbound()
    rec = _northbound_cache.get(code)
    if rec:
        out.update(rec)
        out["_partial"] = False
    return out


def _score_northbound(flow: dict) -> tuple[int, list[dict]]:
    """Score northbound holding changes independently on a 0-15 scale."""
    add_mv = _safe_float(flow.get("add_mv_5d"))
    add_pct = _safe_float(flow.get("add_mv_pct_5d"))
    add_ratio = _safe_float(flow.get("add_ratio_float_5d"))
    if add_mv is None and add_pct is None and add_ratio is None:
        return 0, [{"score": 0, "desc": "北向持股数据缺失", "kind": "neutral"}]

    score = 0
    if add_mv is not None:
        if add_mv >= 5e8:
            score += 6
        elif add_mv >= 1e8:
            score += 4
        elif add_mv > 0:
            score += 2
        elif add_mv <= -3e8:
            score -= 4
        elif add_mv < 0:
            score -= 2

    if add_pct is not None:
        if add_pct >= 20:
            score += 4
        elif add_pct >= 5:
            score += 3
        elif add_pct > 0:
            score += 1
        elif add_pct <= -10:
            score -= 3
        elif add_pct < 0:
            score -= 1

    if add_ratio is not None:
        if add_ratio >= 0.5:
            score += 5
        elif add_ratio >= 0.1:
            score += 3
        elif add_ratio > 0:
            score += 1
        elif add_ratio <= -0.3:
            score -= 3
        elif add_ratio < 0:
            score -= 1

    score = max(0, min(15, score))
    kind = "good" if score >= 10 else ("neutral" if score >= 5 else "warn")
    parts = []
    if add_mv is not None:
        parts.append(f"5日增持市值 {add_mv/1e8:+.2f}亿")
    if add_pct is not None:
        parts.append(f"市值增幅 {add_pct:+.2f}%")
    if add_ratio is not None:
        parts.append(f"占流通股比 {add_ratio:+.3f}%")
    desc = "北向资金 " + "，".join(parts)
    return score, [{"score": score, "desc": desc, "kind": kind}]


# ---------------------------------------------------------------------------
# 机构研报：近 30 天评级热度
# ---------------------------------------------------------------------------

def get_research_rating(symbol: str, days: int = 30) -> dict:
    """Return recent research-report rating summary for one stock."""
    code = _normalize_code(symbol)
    cached = _research_cache.get(code)
    if cached and (time.monotonic() - cached[0]) < _RESEARCH_TTL:
        return cached[1]

    out = {
        "days": days,
        "report_count": 0,
        "buy_count": 0,
        "positive_count": 0,
        "neutral_count": 0,
        "negative_count": 0,
        "institutions": [],
        "latest_reports": [],
        "_partial": True,
    }
    try:
        ak = _ak()
        df = ak.stock_research_report_em(symbol=code)
        if df is not None and not df.empty:
            cutoff = date.today() - timedelta(days=days)
            reports = []
            institutions: set[str] = set()
            buy_count = positive_count = neutral_count = negative_count = 0
            for _, row in df.iterrows():
                d = _parse_date_only(row.get("日期"))
                if d is None or d < cutoff:
                    continue
                rating = _clean_text(row.get("东财评级"))
                title = _clean_text(row.get("报告名称"))
                org = _clean_text(row.get("机构"))
                if org:
                    institutions.add(org)
                if "买入" in rating:
                    buy_count += 1
                    positive_count += 1
                elif "增持" in rating or "推荐" in rating or "强推" in rating:
                    positive_count += 1
                elif "卖出" in rating or "减持" in rating:
                    negative_count += 1
                elif rating:
                    neutral_count += 1
                reports.append({
                    "date": d.isoformat(),
                    "title": title,
                    "rating": rating,
                    "institution": org,
                    "pdf_url": _clean_text(row.get("报告PDF链接")),
                })
            reports.sort(key=lambda x: x["date"], reverse=True)
            out.update({
                "report_count": len(reports),
                "buy_count": buy_count,
                "positive_count": positive_count,
                "neutral_count": neutral_count,
                "negative_count": negative_count,
                "institutions": sorted(institutions)[:12],
                "latest_reports": reports[:3],
                "_partial": False,
            })
    except Exception as e:
        log.debug("stock_research_report_em(%s) failed: %s", code, e)

    if len(_research_cache) >= _MAX_RESEARCH_CACHE:
        oldest_key = min(_research_cache, key=lambda k: _research_cache[k][0])
        _research_cache.pop(oldest_key, None)
    _research_cache[code] = (time.monotonic(), out)
    return out


def _score_research_rating(research: dict) -> tuple[int, list[dict]]:
    """Score recent institution research signal independently on 0-15."""
    count = int(research.get("report_count") or 0)
    if count <= 0:
        return 0, [{"score": 0, "desc": "近 30 天无机构研报", "kind": "neutral"}]

    buy = int(research.get("buy_count") or 0)
    positive = int(research.get("positive_count") or 0)
    negative = int(research.get("negative_count") or 0)
    inst_count = len(research.get("institutions") or [])

    score = 0
    if count >= 10:
        score += 4
    elif count >= 5:
        score += 3
    elif count >= 2:
        score += 2
    else:
        score += 1

    if buy >= 3:
        score += 5
    elif buy >= 1:
        score += 3

    if positive >= 8:
        score += 4
    elif positive >= 3:
        score += 3
    elif positive >= 1:
        score += 1

    if inst_count >= 5:
        score += 2
    elif inst_count >= 2:
        score += 1

    if negative > 0:
        score -= min(4, negative * 2)

    score = max(0, min(15, score))
    kind = "good" if score >= 10 else ("neutral" if score >= 5 else "warn")
    desc = f"近 30 天研报 {count} 篇，买入 {buy} 篇，正面 {positive} 篇，机构 {inst_count} 家"
    if negative:
        desc += f"，负面评级 {negative} 篇"
    return score, [{"score": score, "desc": desc, "kind": kind}]


# ---------------------------------------------------------------------------
# 减持风险：董监高及相关人员持股变动
# ---------------------------------------------------------------------------

def _ensure_insider_changes(days: int = 90):
    """Load recent insider holding changes once per TTL."""
    global _insider_change_cache, _insider_change_ts
    with _insider_change_lock:
        if _insider_change_ts > 0 and (time.monotonic() - _insider_change_ts) < _INSIDER_CHANGE_TTL:
            return
        try:
            ak = _ak()
            df = ak.stock_hold_management_detail_em()
            if df is None or df.empty:
                _insider_change_cache = {}
                _insider_change_ts = time.monotonic()
                return
            cutoff = date.today() - timedelta(days=days)
            grouped: dict[str, dict] = {}
            for _, row in df.iterrows():
                d = _parse_date_only(row.get("日期"))
                if d is None or d < cutoff:
                    continue
                code = str(row.get("代码", "")).strip().zfill(6)
                if not code:
                    continue
                shares = _safe_float(row.get("变动股数"))
                amount = _safe_float(row.get("变动金额"))
                if (shares is None or shares >= 0) and (amount is None or amount >= 0):
                    continue
                amount_abs = abs(amount or 0.0)
                shares_abs = abs(shares or 0.0)
                rec = grouped.setdefault(code, {
                    "reduce_count": 0,
                    "total_reduce_amount": 0.0,
                    "total_reduce_shares": 0.0,
                    "latest_date": "",
                    "events": [],
                    "days": days,
                })
                rec["reduce_count"] += 1
                rec["total_reduce_amount"] += amount_abs
                rec["total_reduce_shares"] += shares_abs
                date_text = d.isoformat()
                if date_text > rec["latest_date"]:
                    rec["latest_date"] = date_text
                rec["events"].append({
                    "date": date_text,
                    "name": _clean_text(row.get("名称")),
                    "person": _clean_text(row.get("变动人")),
                    "position": _clean_text(row.get("职务")),
                    "relation": _clean_text(row.get("变动人与董监高的关系")),
                    "reason": _clean_text(row.get("变动原因")),
                    "shares": shares,
                    "amount": amount,
                    "price": _safe_float(row.get("成交均价")),
                    "ratio": _safe_float(row.get("变动比例")),
                })
            for rec in grouped.values():
                rec["events"].sort(key=lambda x: x.get("date") or "", reverse=True)
                rec["events"] = rec["events"][:5]
            _insider_change_cache = grouped
            _insider_change_ts = time.monotonic()
            log.info("insider holding changes refreshed: %d stocks", len(grouped))
        except Exception as e:
            _insider_change_ts = time.monotonic()
            log.warning("insider holding changes failed: %s", str(e)[:100])


def get_insider_reduction(symbol: str, days: int = 90) -> dict:
    """Return recent insider reduction summary."""
    code = _normalize_code(symbol)
    out = {
        "days": days,
        "reduce_count": 0,
        "total_reduce_amount": 0.0,
        "total_reduce_shares": 0.0,
        "latest_date": "",
        "events": [],
        "_partial": True,
    }
    _ensure_insider_changes(days=days)
    rec = _insider_change_cache.get(code)
    if rec:
        out.update(rec)
        out["_partial"] = False
    return out


def _score_insider_reduction(reduction: dict) -> tuple[int, list[dict]]:
    """Risk score for insider reductions, 0 means no risk and 15 means severe."""
    count = int(reduction.get("reduce_count") or 0)
    amount = _safe_float(reduction.get("total_reduce_amount")) or 0.0
    if count <= 0 and amount <= 0:
        return 0, [{"score": 0, "desc": "近 90 天未发现董监高/相关人员减持", "kind": "good"}]

    score = 0
    if amount >= 5e8:
        score += 10
    elif amount >= 1e8:
        score += 7
    elif amount >= 3e7:
        score += 5
    elif amount > 0:
        score += 3

    if count >= 5:
        score += 4
    elif count >= 2:
        score += 2
    elif count == 1:
        score += 1

    latest = _parse_date_only(reduction.get("latest_date"))
    if latest and (date.today() - latest).days <= 14:
        score += 2

    score = max(0, min(15, score))
    kind = "bad" if score >= 10 else ("warn" if score >= 5 else "neutral")
    desc = f"近 90 天董监高/相关人员减持 {count} 次，估算金额 {amount/1e8:.2f}亿"
    if reduction.get("latest_date"):
        desc += f"，最近 {reduction['latest_date']}"
    return score, [{"score": -score, "desc": desc, "kind": kind}]


# ---------------------------------------------------------------------------
# 行业景气度（行业排名 + 资金流）
# ---------------------------------------------------------------------------

def _ensure_industries():
    """拉取行业 + 概念资金流数据，按涨幅+净流入排序"""
    global _hot_industries, _hot_concepts, _industry_ts
    with _industry_lock:
        if _industry_ts > 0 and (time.monotonic() - _industry_ts) < _INDUSTRY_TTL:
            return
        try:
            ak = _ak()
            # 行业资金流（同花顺源）
            df_ind = ak.stock_fund_flow_industry()
            inds = []
            for _, row in df_ind.iterrows():
                name = str(row.get("行业", "")).strip()
                if not name:
                    continue
                pct = _safe_float(str(row.get("行业-涨跌幅") or "0").replace("%", ""))
                inds.append({
                    "name": name,
                    "change_pct": pct or 0,
                    "net_inflow": _parse_amt(row.get("净额")),
                    "leader": str(row.get("领涨股", "")),
                    "leader_pct": _safe_float(str(row.get("领涨股-涨跌幅") or "0").replace("%", "")),
                    "company_count": int(row.get("公司家数") or 0),
                })
            inds.sort(key=lambda x: (x["change_pct"], x.get("net_inflow") or 0), reverse=True)
            _hot_industries = inds

            # 概念
            df_con = ak.stock_fund_flow_concept()
            cons = []
            for _, row in df_con.iterrows():
                name = str(row.get("行业", "")).strip()
                if not name:
                    continue
                pct = _safe_float(str(row.get("行业-涨跌幅") or "0").replace("%", ""))
                cons.append({
                    "name": name,
                    "change_pct": pct or 0,
                    "net_inflow": _parse_amt(row.get("净额")),
                    "leader": str(row.get("领涨股", "")),
                    "leader_pct": _safe_float(str(row.get("领涨股-涨跌幅") or "0").replace("%", "")),
                    "company_count": int(row.get("公司家数") or 0),
                })
            cons.sort(key=lambda x: (x["change_pct"], x.get("net_inflow") or 0), reverse=True)
            _hot_concepts = cons
            _industry_ts = time.monotonic()
            log.info("行业景气度刷新: %d 个行业 / %d 个概念", len(inds), len(cons))
        except Exception as e:
            _industry_ts = time.monotonic()
            log.warning("行业景气度拉取失败: %s", str(e)[:100])


def get_hot_industries(top_n: int = 20) -> list[dict]:
    """获取热门行业 Top N（按涨幅排序）"""
    _ensure_industries()
    return _hot_industries[:top_n]


def get_hot_concepts(top_n: int = 20) -> list[dict]:
    """获取热门概念 Top N"""
    _ensure_industries()
    return _hot_concepts[:top_n]


def get_industry_rank(industry_name: str) -> Optional[dict]:
    """返回某个行业的排名信息：排名 / 总数 / 涨幅 / 净流入"""
    _ensure_industries()
    if not _hot_industries or not industry_name:
        return None
    for i, ind in enumerate(_hot_industries):
        if ind["name"] == industry_name or ind["name"] in industry_name or industry_name in ind["name"]:
            return {
                "rank": i + 1,
                "total": len(_hot_industries),
                "change_pct": ind["change_pct"],
                "net_inflow": ind.get("net_inflow"),
                "matched_name": ind["name"],
                "leader": ind.get("leader"),
                "leader_pct": ind.get("leader_pct"),
                "company_count": ind.get("company_count"),
                "percentile": round(1 - (i / max(len(_hot_industries), 1)), 4),
            }
    return None


def _score_industry(industry_name: str) -> tuple[int, Optional[dict], list[dict]]:
    """Score industry heat independently on a 0-15 scale."""
    if not industry_name:
        return 0, None, [{"score": 0, "desc": "行业数据缺失", "kind": "neutral"}]
    rank = get_industry_rank(industry_name)
    if not rank:
        return 0, None, [{"score": 0, "desc": f"行业 {industry_name} 未匹配到景气度排名", "kind": "neutral"}]

    total = max(int(rank.get("total") or 1), 1)
    r = max(int(rank.get("rank") or total), 1)
    change_pct = _safe_float(rank.get("change_pct")) or 0.0
    net_inflow = _safe_float(rank.get("net_inflow"))

    score = 0
    if r <= 5:
        score += 8
    elif r / total <= 0.20:
        score += 6
    elif r / total <= 0.50:
        score += 3

    if change_pct >= 3:
        score += 4
    elif change_pct >= 1:
        score += 3
    elif change_pct > 0:
        score += 1
    elif change_pct <= -2:
        score -= 2

    if net_inflow is not None:
        if net_inflow >= 3e8:
            score += 3
        elif net_inflow > 0:
            score += 1
        elif net_inflow <= -3e8:
            score -= 2

    score = max(0, min(15, score))
    kind = "good" if score >= 10 else ("neutral" if score >= 5 else "warn")
    flow_text = "" if net_inflow is None else f"，净流入 {net_inflow/1e8:+.2f}亿"
    desc = f"行业 {rank.get('matched_name') or industry_name} 排名 {r}/{total}，涨跌幅 {change_pct:+.2f}%{flow_text}"
    if rank.get("leader"):
        desc += f"，领涨 {rank['leader']}"
    return score, rank, [{"score": score, "desc": desc, "kind": kind}]


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
    """对单股做基本面 + 资金面综合评估，返回独立的多维评分（不再混合到一个数字）：

      - hard_blocks: 一票否决的原因列表（非空时直接淘汰）
      - quality: 基本面质量分（0-25），看 PE/盘子/亏损
      - flow_score: 资金面分（0-25），看主力净流入/龙虎榜/换手健康度
      - quality_items / flow_items: 各维度的明细（含分数和原因）
      - info, fund_flow, lhb: 原始数据
    """
    info = get_stock_info(symbol)
    if not info["name"] and name:
        info["name"] = name
    if name and ("ST" in name or "*ST" in name):
        info["is_st"] = True

    fund_flow = get_fund_flow(symbol)
    northbound_flow = get_northbound_flow(symbol)
    research_rating = get_research_rating(symbol)
    insider_reduction = get_insider_reduction(symbol)
    lhb = get_lhb_record(symbol)
    industry_score, industry_rank, industry_items = _score_industry(info.get("industry", ""))
    northbound_score, northbound_items = _score_northbound(northbound_flow)
    research_score, research_items = _score_research_rating(research_rating)
    insider_reduction_score, insider_reduction_items = _score_insider_reduction(insider_reduction)

    blocks: list[str] = []

    # === 一票否决（hard_blocks）===
    if info.get("is_st"):
        blocks.append("ST 风险股")

    days_listed = info.get("days_listed")
    if days_listed is not None and days_listed < 60:
        blocks.append(f"上市仅 {days_listed} 天（次新股）")

    float_mv = info.get("float_mv")
    if float_mv is not None and 0 < float_mv < 30e8:
        blocks.append(f"流通市值仅 {float_mv/1e8:.1f} 亿（小盘风险高）")

    pe = info.get("pe")
    if pe is not None:
        if pe < -100:  # 严重亏损
            blocks.append(f"PE={pe:.0f}（严重亏损）")
        elif pe > 200:
            blocks.append(f"PE={pe:.0f}（估值严重过高）")

    if insider_reduction_score >= 10:
        amount = _safe_float(insider_reduction.get("total_reduce_amount")) or 0.0
        blocks.append(f"董监高/相关人员近 90 天大额减持 {amount/1e8:.2f} 亿")

    # 龙虎榜负面：跌幅净卖出
    for r in lhb:
        if "跌幅" in r["reason"] and r["net_buy"] < -1e7:
            blocks.append(f"龙虎榜异动卖出：{r['reason']}")
            break

    # === 基本面质量分（0-25）===
    quality_items: list[dict] = []
    quality = 0

    # 估值（10 分）
    if pe is not None:
        if 0 < pe <= 20:
            quality += 10
            quality_items.append({"score": 10, "desc": f"PE={pe:.1f}（低估值）", "kind": "good"})
        elif 20 < pe <= 35:
            quality += 7
            quality_items.append({"score": 7, "desc": f"PE={pe:.1f}（合理估值）", "kind": "good"})
        elif 35 < pe <= 60:
            quality += 4
            quality_items.append({"score": 4, "desc": f"PE={pe:.1f}（估值偏高）", "kind": "neutral"})
        elif 60 < pe <= 100:
            quality += 1
            quality_items.append({"score": 1, "desc": f"PE={pe:.1f}（估值高）", "kind": "warn"})
        elif 100 < pe <= 200:
            quality_items.append({"score": 0, "desc": f"PE={pe:.1f}（估值过高）", "kind": "warn"})
        else:
            quality_items.append({"score": 0, "desc": f"PE={pe:.0f}（亏损中）", "kind": "warn"})
    else:
        quality_items.append({"score": 0, "desc": "PE 数据缺失", "kind": "neutral"})

    # 盘子（10 分）
    if float_mv is not None:
        fmv_yi = float_mv / 1e8
        if 50 <= fmv_yi <= 300:
            quality += 10
            quality_items.append({"score": 10, "desc": f"流通市值 {fmv_yi:.0f}亿（机构友好盘子）", "kind": "good"})
        elif 300 < fmv_yi <= 1000:
            quality += 7
            quality_items.append({"score": 7, "desc": f"流通市值 {fmv_yi:.0f}亿（机构重仓）", "kind": "good"})
        elif 30 <= fmv_yi < 50:
            quality += 5
            quality_items.append({"score": 5, "desc": f"流通市值 {fmv_yi:.0f}亿（中小盘）", "kind": "neutral"})
        elif fmv_yi > 1000:
            quality += 3
            quality_items.append({"score": 3, "desc": f"流通市值 {fmv_yi:.0f}亿（超大盘，涨速慢）", "kind": "neutral"})
    else:
        quality_items.append({"score": 0, "desc": "市值数据缺失", "kind": "neutral"})

    # PB 估值（5 分）
    pb = info.get("pb")
    if pb is not None and pb > 0:
        if pb <= 2:
            quality += 5
            quality_items.append({"score": 5, "desc": f"PB={pb:.2f}（低估值）", "kind": "good"})
        elif 2 < pb <= 5:
            quality += 3
            quality_items.append({"score": 3, "desc": f"PB={pb:.2f}（合理）", "kind": "neutral"})
        elif pb > 10:
            quality_items.append({"score": 0, "desc": f"PB={pb:.2f}（高估）", "kind": "warn"})

    # === 资金面分（0-25）===
    flow_items: list[dict] = []
    flow_score = 0

    today_net = fund_flow.get("today_net")
    if today_net is not None:
        if today_net > 2e8:
            flow_score += 12
            flow_items.append({"score": 12, "desc": f"主力净流入 {today_net/1e8:.2f}亿（资金强势）", "kind": "good"})
        elif today_net > 5e7:
            flow_score += 8
            flow_items.append({"score": 8, "desc": f"主力净流入 {today_net/1e8:.2f}亿", "kind": "good"})
        elif today_net > 0:
            flow_score += 4
            flow_items.append({"score": 4, "desc": f"主力小幅净流入 {today_net/1e8:.2f}亿", "kind": "neutral"})
        elif today_net > -5e7:
            flow_items.append({"score": 0, "desc": f"主力净流出 {abs(today_net)/1e8:.2f}亿", "kind": "warn"})
        else:
            flow_items.append({"score": 0, "desc": f"主力大幅净流出 {abs(today_net)/1e8:.2f}亿", "kind": "bad"})
    else:
        flow_items.append({"score": 0, "desc": "资金流数据缺失", "kind": "neutral"})

    # 换手率（5 分）
    tor = fund_flow.get("turnover_rate")
    if tor is not None:
        if 3 <= tor <= 10:
            flow_score += 5
            flow_items.append({"score": 5, "desc": f"换手 {tor:.1f}%（健康活跃）", "kind": "good"})
        elif 10 < tor <= 20:
            flow_score += 3
            flow_items.append({"score": 3, "desc": f"换手 {tor:.1f}%（活跃偏高）", "kind": "neutral"})
        elif tor > 20:
            flow_items.append({"score": 0, "desc": f"换手 {tor:.1f}%（过热风险）", "kind": "warn"})
        elif tor < 1:
            flow_items.append({"score": 0, "desc": f"换手仅 {tor:.1f}%（流动性差）", "kind": "warn"})

    # 龙虎榜机构买入（8 分）
    for r in lhb:
        if r["net_buy"] > 5e7 and "机构" in r["interpret"]:
            flow_score += 8
            flow_items.append({
                "score": 8,
                "desc": f"龙虎榜：{r['date']} 机构净买入 {r['net_buy']/1e8:.2f}亿",
                "kind": "good"
            })
            break

    quality = max(0, min(25, quality))
    flow_score = max(0, min(25, flow_score))

    return {
        "hard_blocks": blocks,
        "quality": quality,
        "flow_score": flow_score,
        "industry_score": industry_score,
        "northbound_score": northbound_score,
        "research_score": research_score,
        "insider_reduction_score": insider_reduction_score,
        "quality_items": quality_items,
        "flow_items": flow_items,
        "industry_items": industry_items,
        "northbound_items": northbound_items,
        "research_items": research_items,
        "insider_reduction_items": insider_reduction_items,
        "industry_rank": industry_rank,
        "info": info,
        "fund_flow": fund_flow,
        "northbound_flow": northbound_flow,
        "research_rating": research_rating,
        "insider_reduction": insider_reduction,
        "lhb": lhb,
    }


def clear_cache():
    """清除所有缓存"""
    global _info_cache, _flow_cache, _lhb_cache, _lhb_ts, _market_flow_cache, _market_flow_ts
    global _hot_industries, _hot_concepts, _industry_ts
    global _northbound_cache, _northbound_ts
    global _insider_change_cache, _insider_change_ts
    global _research_cache
    _info_cache.clear()
    _flow_cache.clear()
    _research_cache.clear()
    _market_flow_cache = {}
    _market_flow_ts = 0.0
    _northbound_cache = {}
    _northbound_ts = 0.0
    _insider_change_cache = {}
    _insider_change_ts = 0.0
    _lhb_cache = {}
    _lhb_ts = 0.0
    _hot_industries = []
    _hot_concepts = []
    _industry_ts = 0.0
