"""Tests for order manager."""

import pytest

from libs.execution.order_manager import OrderManager, OrderStatus, OrderType


def test_create_order():
    """Test order creation."""
    manager = OrderManager()
    
    order = manager.create_order(
        account_id="acc1",
        symbol="600519.SH",
        side="BUY",
        quantity=100,
        order_type=OrderType.LIMIT,
        price=1700.0,
    )
    
    assert order.order_id.startswith("ORD-")
    assert order.symbol == "600519.SH"
    assert order.quantity == 100
    assert order.status == OrderStatus.PENDING


def test_submit_order():
    """Test order submission."""
    manager = OrderManager()
    
    order = manager.create_order(
        account_id="acc1",
        symbol="600519.SH",
        side="BUY",
        quantity=100,
        price=1700.0,
    )
    
    success = manager.submit_order(order.order_id, broker_order_id="BROKER-123")
    
    assert success is True
    assert order.status == OrderStatus.SUBMITTED
    assert order.broker_order_id == "BROKER-123"


def test_add_fill():
    """Test adding fill to order."""
    manager = OrderManager()
    
    order = manager.create_order(
        account_id="acc1",
        symbol="600519.SH",
        side="BUY",
        quantity=100,
        price=1700.0,
    )
    
    manager.submit_order(order.order_id)
    
    fill = manager.add_fill(
        order_id=order.order_id,
        quantity=50,
        price=1698.0,
        commission=5.0,
    )
    
    assert fill is not None
    assert order.filled_quantity == 50
    assert order.status == OrderStatus.PARTIAL_FILLED


def test_full_fill():
    """Test complete order fill."""
    manager = OrderManager()
    
    order = manager.create_order(
        account_id="acc1",
        symbol="600519.SH",
        side="BUY",
        quantity=100,
        price=1700.0,
    )
    
    manager.submit_order(order.order_id)
    manager.add_fill(order.order_id, 100, 1698.0, 5.0)
    
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 100


def test_cancel_order():
    """Test order cancellation."""
    manager = OrderManager()
    
    order = manager.create_order(
        account_id="acc1",
        symbol="600519.SH",
        side="BUY",
        quantity=100,
        price=1700.0,
    )
    
    success = manager.cancel_order(order.order_id, reason="User cancelled")
    
    assert success is True
    assert order.status == OrderStatus.CANCELLED
    assert order.error_message == "User cancelled"


def test_get_active_orders():
    """Test getting active orders."""
    manager = OrderManager()
    
    # Create multiple orders
    order1 = manager.create_order("acc1", "600519.SH", "BUY", 100, price=1700.0)
    order2 = manager.create_order("acc1", "000001.SZ", "BUY", 1000, price=11.0)
    order3 = manager.create_order("acc1", "300750.SZ", "SELL", 100, price=230.0)
    
    manager.submit_order(order1.order_id)
    manager.submit_order(order2.order_id)
    manager.cancel_order(order3.order_id)
    
    active = manager.get_active_orders()
    
    assert len(active) == 2
    assert order3.order_id not in [o.order_id for o in active]
