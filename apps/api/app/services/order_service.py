"""Order lifecycle service: create, simulate, and persist orders."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.repositories import (
    AuditLogRepository,
    OrderRepository,
    PortfolioRepository,
    TradeFillRepository,
)
from apps.api.app.services.sample_data import BUYABLE_SYMBOLS, ORDER_SIDES
from libs.execution.a_share_rules import OrderSide as ARuleSide, check_order
from libs.quant_core.enums import AuditAction, OrderSource, OrderStatus, OrderType
from libs.quant_core.models import AuditLog, Order, Position as _PositionDC, TradeFill


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class OrderService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._fills = TradeFillRepository(session)
        self._audit = AuditLogRepository(session)
        self._portfolio = PortfolioRepository(session)
        self._settings = get_settings()

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: int,
        source: str,
        actor: str,
    ) -> Order:
        if side not in ORDER_SIDES:
            raise ValueError(f"Unsupported side: {side}")
        if symbol not in BUYABLE_SYMBOLS:
            raise ValueError(f"Unknown symbol: {symbol}")
        if order_type not in (OrderType.LIMIT.value, OrderType.MARKET.value):
            raise ValueError(f"Unsupported order_type: {order_type}")

        # A-share specific rule check (T+1, lot size, price limit, etc.)
        avail = 0
        if side == "SELL":
            for pos in self._portfolio.list_positions():
                if pos.symbol == symbol:
                    avail = pos.available_quantity
                    break

        prev_close = self._lookup_prev_close(symbol)
        result = check_order(
            symbol=symbol,
            side=ARuleSide(side),
            quantity=quantity,
            price=price,
            prev_close=prev_close,
            available_quantity=avail,
            is_st=self._is_st(symbol),
        )
        if not result.ok:
            raise ValueError(f"违反A股交易规则: {result.message}")

        if price <= 0:
            raise ValueError("price must be positive")
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        # Risk-engine pre-trade evaluation (records BLOCK/WARN events)
        from apps.api.app.services.risk_service import RiskService
        risk_svc = RiskService(self._session)
        positions = self._portfolio.list_positions()
        summary = self._portfolio.get_summary()
        total_value = summary.total_asset if summary else sum(p.market_value for p in positions) + 1
        allowed, _events = risk_svc.evaluate_order(
            symbol=symbol, side=side, price=price, quantity=quantity,
            positions=positions, portfolio_total_value=total_value,
        )
        if not allowed:
            raise ValueError("风控引擎拦截：违反组合约束规则（详情见风控事件）")

        now = _now()
        order = Order(
            order_id=str(uuid.uuid4()),
            account_id=self._settings.default_account_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            filled_quantity=0,
            status=OrderStatus.PENDING.value,
            source=source,
            broker_order_id=None,
            reject_reason=None,
            created_at=now,
            updated_at=now,
        )
        self._orders.save(order)

        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action=AuditAction.ORDER_SUBMITTED.value,
            actor=actor,
            resource_type="order",
            resource_id=order.order_id,
            details={"symbol": symbol, "side": side, "quantity": quantity, "price": price},
            created_at=now,
        ))

        # Forward to QMT gateway when live trading is enabled (Design Doc §5.5).
        # Risk has already approved; the gateway only translates protocols.
        # Flush so subsequent update_status SELECTs see the new row
        # (session.autoflush is False).
        self._session.flush()
        order = self._maybe_forward_to_gateway(order, actor)
        return order

    def _maybe_forward_to_gateway(self, order: Order, actor: str) -> Order:
        """Try to push the order to QMTClient. No-op if not configured / disabled.

        - On success: stores gateway's order_id as broker_order_id and updates
          local status to ACCEPTED (or whatever the gateway returns).
        - On failure: keeps local status PENDING; audit-logs the issue. Does
          NOT raise — local order remains as a paper-trade for reconciliation.
        """
        from apps.api.app.services.qmt_client import (
            QMTClient, QMTClientError, QMTClientUnavailable,
        )
        client = QMTClient()
        if not client.is_configured():
            return order

        try:
            resp = client.place_order(
                symbol=order.symbol, side=order.side, quantity=order.quantity,
                order_type=order.order_type, price=order.price,
                client_order_id=order.order_id,
            )
        except (QMTClientUnavailable, QMTClientError) as exc:
            self._audit.save(AuditLog(
                log_id=str(uuid.uuid4()),
                action="ORDER_GATEWAY_FAILED",
                actor=actor,
                resource_type="order",
                resource_id=order.order_id,
                details={"error": str(exc)},
                created_at=_now(),
            ))
            return order

        broker_id = resp.get("order_id")
        # Map gateway status → local status enum
        gw_status = resp.get("status", "ACCEPTED").upper()
        if gw_status == "REJECTED":
            local_status = OrderStatus.REJECTED.value
        elif gw_status == "FILLED":
            local_status = OrderStatus.FILLED.value
        elif gw_status == "CANCELLED":
            local_status = OrderStatus.CANCELLED.value
        elif gw_status == "PARTIAL":
            local_status = OrderStatus.PARTIAL_FILLED.value
        else:  # ACCEPTED / unknown
            local_status = OrderStatus.PENDING.value

        self._orders.update_status(
            order_id=order.order_id,
            status=local_status,
            broker_order_id=broker_id,
            filled_quantity=int(resp.get("filled_quantity", 0)),
            reject_reason=resp.get("error_message"),
            updated_at=_now(),
        )
        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action="ORDER_FORWARDED_TO_GATEWAY",
            actor=actor,
            resource_type="order",
            resource_id=order.order_id,
            details={"broker_order_id": broker_id, "gateway_status": gw_status},
            created_at=_now(),
        ))
        return self._orders.get(order.order_id) or order

    def cancel_order(self, order_id: str, actor: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")
        if order.status not in (OrderStatus.PENDING.value, OrderStatus.PARTIAL_FILLED.value):
            raise ValueError(f"Order {order_id} cannot be cancelled (status={order.status})")

        # Forward cancel to gateway if order was forwarded earlier
        if order.broker_order_id:
            from apps.api.app.services.qmt_client import (
                QMTClient, QMTClientError, QMTClientUnavailable,
            )
            client = QMTClient()
            if client.is_configured():
                try:
                    client.cancel_order(order.broker_order_id)
                except (QMTClientUnavailable, QMTClientError) as exc:
                    self._audit.save(AuditLog(
                        log_id=str(uuid.uuid4()),
                        action="ORDER_GATEWAY_CANCEL_FAILED",
                        actor=actor,
                        resource_type="order",
                        resource_id=order_id,
                        details={"error": str(exc)},
                        created_at=_now(),
                    ))
                    # proceed to mark local as cancelled — caller can reconcile

        now = _now()
        self._orders.update_status(
            order_id=order_id,
            status=OrderStatus.CANCELLED.value,
            broker_order_id=order.broker_order_id,
            filled_quantity=order.filled_quantity,
            reject_reason=None,
            updated_at=now,
        )
        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action=AuditAction.ORDER_CANCELLED.value,
            actor=actor,
            resource_type="order",
            resource_id=order_id,
            details={},
            created_at=now,
        ))
        return self._orders.get(order_id)  # type: ignore[return-value]

    def simulate_fill(self, order_id: str, fill_price: float, fill_quantity: int) -> TradeFill:
        """Simulated fill for paper-trading mode.

        Side-effects (for true accounting):
        1. Persist a TradeFill row.
        2. Update parent Order status & filled_quantity.
        3. Recompute the Position (qty + weighted avg_cost + realized_pnl).
        4. Update PortfolioSummary cash + market_value.
        5. Audit-log the fill event.
        """
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")

        now = _now()
        commission = round(fill_price * fill_quantity * 0.0003, 4)
        fill = TradeFill(
            fill_id=str(uuid.uuid4()),
            order_id=order_id,
            symbol=order.symbol,
            fill_price=fill_price,
            fill_quantity=fill_quantity,
            fill_time=now,
            commission=commission,
        )
        self._fills.save(fill)

        new_filled = order.filled_quantity + fill_quantity
        new_status = (
            OrderStatus.FILLED.value
            if new_filled >= order.quantity
            else OrderStatus.PARTIAL_FILLED.value
        )
        self._orders.update_status(
            order_id=order_id,
            status=new_status,
            broker_order_id=order.broker_order_id,
            filled_quantity=new_filled,
            reject_reason=None,
            updated_at=now,
        )

        # 3 + 4) Recompute portfolio state ----------------------------------
        self._apply_fill_to_portfolio(order, fill)

        # 5) Audit log ------------------------------------------------------
        self._audit.save(AuditLog(
            log_id=str(uuid.uuid4()),
            action=AuditAction.FILL_RECEIVED.value,
            actor="simulator",
            resource_type="order",
            resource_id=order.order_id,
            details={
                "fill_id": fill.fill_id,
                "fill_price": fill_price,
                "fill_quantity": fill_quantity,
                "commission": commission,
                "side": order.side,
                "symbol": order.symbol,
            },
            created_at=now,
        ))
        return fill

    def _apply_fill_to_portfolio(self, order: Order, fill: TradeFill) -> None:
        """Update positions & cash from a fill — paper-trading accounting."""
        from datetime import datetime
        now = datetime.now()
        account_id = self._settings.default_account_id

        existing = self._portfolio.get_position(account_id, order.symbol)
        side = order.side.upper()

        if side == "BUY":
            old_qty = existing.quantity if existing else 0
            old_cost_basis = (existing.avg_cost * old_qty) if existing else 0.0
            new_qty = old_qty + fill.fill_quantity
            new_cost_basis = old_cost_basis + fill.fill_price * fill.fill_quantity
            new_avg_cost = (new_cost_basis / new_qty) if new_qty > 0 else fill.fill_price
            new_market_value = fill.fill_price * new_qty
            new_unrealized = new_market_value - new_cost_basis

            self._portfolio.upsert_position(_PositionDC(
                position_id=existing.position_id if existing else f"pos-{order.symbol}",
                account_id=account_id,
                symbol=order.symbol,
                quantity=new_qty,
                # T+1: bought today is locked, only previously held is available
                available_quantity=existing.available_quantity if existing else 0,
                avg_cost=round(new_avg_cost, 4),
                market_value=round(new_market_value, 2),
                unrealized_pnl=round(new_unrealized, 2),
                realized_pnl=existing.realized_pnl if existing else 0.0,
                updated_at=now,
            ))

        elif side == "SELL":
            if existing is None or existing.quantity < fill.fill_quantity:
                # Defensive: should have been blocked by A-share rule check
                return
            old_qty = existing.quantity
            old_avg_cost = existing.avg_cost
            new_qty = old_qty - fill.fill_quantity
            realized_gain = (fill.fill_price - old_avg_cost) * fill.fill_quantity - fill.commission
            new_realized = (existing.realized_pnl or 0.0) + realized_gain

            if new_qty == 0:
                self._portfolio.remove_position(account_id, order.symbol)
            else:
                new_market_value = fill.fill_price * new_qty
                new_unrealized = (fill.fill_price - old_avg_cost) * new_qty
                self._portfolio.upsert_position(_PositionDC(
                    position_id=existing.position_id,
                    account_id=account_id,
                    symbol=order.symbol,
                    quantity=new_qty,
                    available_quantity=max(0, existing.available_quantity - fill.fill_quantity),
                    avg_cost=old_avg_cost,
                    market_value=round(new_market_value, 2),
                    unrealized_pnl=round(new_unrealized, 2),
                    realized_pnl=round(new_realized, 2),
                    updated_at=now,
                ))

        # Update portfolio cash + total
        summary = self._portfolio.get_summary()
        if summary is not None:
            cash_delta = (
                -fill.fill_price * fill.fill_quantity - fill.commission
                if side == "BUY"
                else fill.fill_price * fill.fill_quantity - fill.commission
            )
            new_cash = summary.cash + cash_delta
            positions_total = sum(p.market_value for p in self._portfolio.list_positions())
            updated = type(summary)(
                account_id=summary.account_id,
                portfolio_name=summary.portfolio_name,
                base_currency=summary.base_currency,
                total_asset=new_cash + positions_total,
                cash=new_cash,
                market_value=positions_total,
                daily_pnl=summary.daily_pnl,
                total_pnl=summary.total_pnl,
                updated_at=now,
            )
            self._portfolio.save_summary(updated)

    def get_order(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")
        return order

    def list_orders(self, limit: int = 50) -> list[Order]:
        return self._orders.list_by_account(
            self._settings.default_account_id, limit=limit
        )

    def list_fills(self, order_id: str) -> list[TradeFill]:
        return self._fills.list_by_order(order_id)

    # ------------------------------------------------------------------
    # Internal lookups (best-effort, fall back to safe defaults)
    # ------------------------------------------------------------------
    def _lookup_prev_close(self, symbol: str) -> float:
        """Best-effort lookup of yesterday's close from sample data."""
        try:
            from apps.api.app.services.sample_data import REALTIME_QUOTES
            q = REALTIME_QUOTES.get(symbol)
            if q and q.last_price:
                return q.last_price
        except Exception:  # noqa: BLE001
            pass
        return 0.0  # 0 disables the price-limit check

    def _is_st(self, symbol: str) -> bool:
        try:
            from apps.api.app.services.sample_data import INSTRUMENTS
            for inst in INSTRUMENTS:
                if inst.symbol == symbol:
                    return bool(inst.is_st)
        except Exception:  # noqa: BLE001
            pass
        return False
