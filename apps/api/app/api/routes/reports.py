"""Markdown report export — daily portfolio + advisor + risk events."""

from __future__ import annotations

from datetime import datetime
from io import StringIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from apps.api.app.db.session import get_db
from apps.api.app.services.advisor_service import AdvisorService
from apps.api.app.db.repositories import (
    AuditLogRepository,
    NewsRepository,
    PortfolioRepository,
    RiskEventRepository,
    SignalRepository,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/daily", response_class=PlainTextResponse)
def daily_report(
    fmt: str = Query("markdown", description="markdown | html"),
    db: Session = Depends(get_db),
):
    """Generate a daily report aggregating positions, advice, signals, news, risk events."""
    out = StringIO()
    now = datetime.now()

    portfolio = PortfolioRepository(db)
    summary = portfolio.get_summary()
    positions = portfolio.list_positions()
    risk_events = RiskEventRepository(db).list_recent(limit=20)
    signals = SignalRepository(db).list_latest_per_symbol()
    news = NewsRepository(db).list_articles(limit=10)
    audit = AuditLogRepository(db).list_recent(limit=20) if hasattr(AuditLogRepository(db), "list_recent") else []

    out.write(f"# 量化交易日报 — {now:%Y-%m-%d %H:%M}\n\n")

    # ---- Portfolio ---------------------------------------------------------
    out.write("## 1. 组合概览\n\n")
    if summary:
        out.write(f"- **总资产**：¥{summary.total_asset:,.2f}\n")
        out.write(f"- **可用现金**：¥{summary.cash:,.2f}\n")
        out.write(f"- **持仓市值**：¥{summary.market_value:,.2f}\n")
        out.write(f"- **当日盈亏**：¥{summary.daily_pnl:+,.2f}\n")
        out.write(f"- **累计盈亏**：¥{summary.total_pnl:+,.2f}\n\n")
    else:
        out.write("_暂无组合快照_\n\n")

    # ---- Positions --------------------------------------------------------
    out.write("## 2. 持仓明细\n\n")
    if positions:
        out.write("| 代码 | 持仓量 | 可用 | 成本价 | 市值 | 浮动盈亏 |\n")
        out.write("|---|---:|---:|---:|---:|---:|\n")
        for p in positions:
            out.write(
                f"| {p.symbol} | {p.quantity:,} | {p.available_quantity:,} | "
                f"{p.avg_cost:,.2f} | ¥{p.market_value:,.2f} | "
                f"¥{p.unrealized_pnl:+,.2f} |\n"
            )
        out.write("\n")
    else:
        out.write("_无持仓_\n\n")

    # ---- Advisor ----------------------------------------------------------
    out.write("## 3. 智能交易建议\n\n")
    try:
        report = AdvisorService(db).build()
        out.write(f"_由 {report.summary.get('agents_used', 0)} 个 Agent 综合输出，"
                  f"共 {len(report.items)} 条建议_\n\n")
        if report.items:
            out.write("| 标的 | 操作 | 优先级 | 置信度 | 理由 |\n")
            out.write("|---|---|---:|---:|---|\n")
            for it in report.items:
                out.write(
                    f"| {it.symbol} | **{it.action}** | P{it.priority} | "
                    f"{it.confidence:.0%} | {it.reason[:80]} |\n"
                )
            out.write("\n")
    except Exception as exc:  # noqa: BLE001
        out.write(f"_advisor 不可用: {exc}_\n\n")

    # ---- Signals ----------------------------------------------------------
    out.write("## 4. 最新技术信号\n\n")
    if signals:
        out.write("| 标的 | 类型 | 原始分 | 置信度 | 时间 |\n")
        out.write("|---|---|---:|---:|---|\n")
        for s in signals[:20]:
            out.write(
                f"| {s.symbol} | {s.signal_type} | {s.raw_score:+.3f} | "
                f"{s.confidence:.0%} | {s.as_of_time:%H:%M:%S} |\n"
            )
        out.write("\n")
    else:
        out.write("_暂无信号_\n\n")

    # ---- Risk events ------------------------------------------------------
    out.write("## 5. 风控事件\n\n")
    if risk_events:
        for ev in risk_events:
            icon = "🔴" if ev.severity == "HIGH" else "🟠"
            out.write(f"- {icon} **{ev.created_at:%H:%M:%S}** [{ev.decision}] "
                      f"{ev.symbol or '-'} — {ev.message}\n")
        out.write("\n")
    else:
        out.write("_无风控事件_\n\n")

    # ---- News -------------------------------------------------------------
    out.write("## 6. 近期新闻\n\n")
    if news:
        for n in news[:10]:
            symbols = ", ".join(n.symbols or []) or "-"
            out.write(f"- **{n.published_at:%m-%d %H:%M}** [{n.source}] "
                      f"{n.title} _(标的：{symbols})_\n")
        out.write("\n")
    else:
        out.write("_无新闻_\n\n")

    out.write(f"\n---\n*报告生成时间：{now:%Y-%m-%d %H:%M:%S}*\n")

    text = out.getvalue()
    if fmt == "html":
        try:
            import markdown as _md  # type: ignore
            html = _md.markdown(text, extensions=["tables"])
            return PlainTextResponse(html, media_type="text/html; charset=utf-8")
        except ImportError:
            pass  # fall through to markdown
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")
