"""提醒服务 — 检查价格触发条件，发送飞书通知"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from apps.api.app.db.models import AlertORM, PositionORM
from apps.api.app.services import feishu_service

log = logging.getLogger("quant.alert")

# 持仓告警去重：(symbol, kind) -> 最后一次发送时间
# kind = "stop_loss" | "take_profit"
_position_alert_state: dict[tuple[str, str], datetime] = {}
_position_alert_lock = threading.Lock()
_POSITION_ALERT_COOLDOWN = timedelta(hours=2)  # 同一只股票同类告警 2 小时内不重发


def _send_feishu_async(fn, *args, **kwargs):
    """飞书发送移到后台线程，避免阻塞 quote_loop"""
    threading.Thread(
        target=lambda: fn(*args, **kwargs),
        daemon=True,
        name="feishu-async",
    ).start()


def check_price_alerts(db: Session, quotes: list[dict]) -> list[dict]:
    """
    检查所有未触发的价格提醒，触发后发送飞书通知。
    返回本次触发的提醒列表。
    """
    if not quotes:
        return []

    quote_map = {q["symbol"]: q for q in quotes}
    triggered = []

    alerts = db.query(AlertORM).filter(
        AlertORM.triggered == False,
        AlertORM.alert_type.in_(["price_above", "price_below"]),
    ).all()

    for alert in alerts:
        q = quote_map.get(alert.symbol)
        if not q or not alert.target_price:
            continue

        price = q.get("price", 0)
        # 防止启动时缓存空导致 price=0 误触发
        if price <= 0:
            continue

        hit = False
        if alert.alert_type == "price_above" and price >= alert.target_price:
            hit = True
        elif alert.alert_type == "price_below" and price <= alert.target_price:
            hit = True

        if hit:
            alert.triggered = True
            alert.triggered_at = datetime.now(timezone.utc).replace(tzinfo=None)
            # 飞书发送移到后台线程，发送结果不阻塞主流程
            try:
                feishu_service.send_price_alert(
                    symbol=alert.symbol,
                    name=alert.name or q.get("name", alert.symbol),
                    price=price,
                    target=alert.target_price,
                    alert_type=alert.alert_type,
                )
                alert.feishu_sent = True
            except Exception as e:
                log.warning("飞书价格提醒发送失败: %s", e)
                alert.feishu_sent = False
            triggered.append({
                "id": alert.id,
                "symbol": alert.symbol,
                "name": alert.name,
                "alert_type": alert.alert_type,
                "target_price": alert.target_price,
                "current_price": price,
            })
            log.info("价格提醒触发: %s %s @ %.2f (target=%.2f)",
                     alert.symbol, alert.alert_type, price, alert.target_price)

    db.commit()
    return triggered


def check_position_alerts(db: Session, quotes: list[dict]) -> list[dict]:
    """
    检查持仓的止损/止盈条件，触发后发送飞书通知。
    使用 PositionORM.last_alert_at 持久化去重，重启也不会重复发送。
    """
    if not quotes:
        return []

    quote_map = {q["symbol"]: q for q in quotes}
    triggered = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    dirty = False

    positions = db.query(PositionORM).all()
    for pos in positions:
        q = quote_map.get(pos.symbol)
        if not q or pos.avg_cost <= 0:
            continue

        price = q.get("price", 0)
        # 防止启动时缓存空导致 price=0 误触发 -100% 止损
        if price <= 0:
            continue

        pnl_pct = (price - pos.avg_cost) / pos.avg_cost * 100

        kind = None
        reason = None
        if pos.stop_loss_pct > 0 and pnl_pct <= -pos.stop_loss_pct * 100:
            kind = "stop_loss"
            reason = f"浮亏已达 {pnl_pct:.2f}%，触发止损线（-{pos.stop_loss_pct*100:.0f}%），建议立即卖出！"
        elif pos.take_profit_pct > 0 and pnl_pct >= pos.take_profit_pct * 100:
            kind = "take_profit"
            reason = f"浮盈已达 {pnl_pct:.2f}%，触发止盈线（+{pos.take_profit_pct*100:.0f}%），可考虑分批止盈。"

        if not kind:
            continue

        # 双层去重：内存 (2 小时) + DB (上次同类告警时间)
        # 1) 内存级冷却（防 3 秒内连续触发）
        mem_key = (pos.symbol, kind)
        with _position_alert_lock:
            last_mem = _position_alert_state.get(mem_key)
            if last_mem and (now - last_mem) < _POSITION_ALERT_COOLDOWN:
                continue
            _position_alert_state[mem_key] = now

        # 2) DB 级冷却（重启后仍生效）
        if (pos.last_alert_kind == kind and pos.last_alert_at
                and (now - pos.last_alert_at) < _POSITION_ALERT_COOLDOWN):
            continue

        # 写 DB 持久化
        pos.last_alert_at = now
        pos.last_alert_kind = kind
        dirty = True

        try:
            feishu_service.send_sell_alert(
                symbol=pos.symbol,
                name=pos.name or q.get("name", pos.symbol),
                price=price,
                avg_cost=pos.avg_cost,
                pnl_pct=pnl_pct,
                reason=reason,
            )
        except Exception as e:
            log.warning("飞书持仓提醒发送失败: %s", e)

        triggered.append({
            "symbol": pos.symbol,
            "name": pos.name,
            "price": price,
            "avg_cost": pos.avg_cost,
            "pnl_pct": round(pnl_pct, 2),
            "reason": reason,
            "kind": kind,
        })
        log.info("持仓提醒触发: %s %s pnl=%.2f%%", pos.symbol, kind, pnl_pct)

    if dirty:
        db.commit()
    return triggered


def reset_position_alert_state(symbol: str | None = None):
    """删除/调整持仓后调用，清理对应的告警去重状态。"""
    with _position_alert_lock:
        if symbol is None:
            _position_alert_state.clear()
        else:
            for key in list(_position_alert_state.keys()):
                if key[0] == symbol:
                    _position_alert_state.pop(key, None)


def create_agent_alert(db: Session, analysis: dict) -> AlertORM | None:
    """根据 Agent 分析结果创建提醒并发送飞书"""
    action = analysis.get("action", "HOLD")
    symbol = analysis.get("symbol", "")
    name = analysis.get("name", symbol)

    if action not in ("BUY", "SELL"):
        return None

    alert_type = "agent_buy" if action == "BUY" else "agent_sell"
    message = analysis.get("reason", "")

    # 避免重复创建同一股票同类型的未触发提醒
    existing = db.query(AlertORM).filter(
        AlertORM.symbol == symbol,
        AlertORM.alert_type == alert_type,
        AlertORM.triggered == False,
    ).first()
    if existing:
        return existing

    alert = AlertORM(
        symbol=symbol,
        name=name,
        alert_type=alert_type,
        target_price=analysis.get("buy_price_low") if action == "BUY" else analysis.get("stop_loss"),
        message=message,
    )
    db.add(alert)
    db.flush()

    # 立即发送飞书
    if action == "BUY":
        sent = feishu_service.send_buy_alert(
            symbol=symbol,
            name=name,
            price=analysis.get("current_price", 0),
            buy_low=analysis.get("buy_price_low", 0),
            buy_high=analysis.get("buy_price_high", 0),
            stop_loss=analysis.get("stop_loss", 0),
            take_profit=analysis.get("take_profit", 0),
            reason=message,
            confidence=analysis.get("confidence", 0),
        )
        alert.feishu_sent = sent

    db.commit()
    return alert
