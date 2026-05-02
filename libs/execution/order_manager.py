"""Order management and execution tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4


class OrderStatus(str, Enum):
    """Order status."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class OrderType(str, Enum):
    """Order type."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


@dataclass
class Order:
    """Order representation."""
    order_id: str
    account_id: str
    symbol: str
    side: str  # BUY or SELL
    order_type: OrderType
    quantity: int
    price: Optional[float]
    status: OrderStatus
    filled_quantity: int = 0
    filled_avg_price: float = 0.0
    commission: float = 0.0
    created_at: datetime = None
    updated_at: datetime = None
    broker_order_id: Optional[str] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()


@dataclass
class Fill:
    """Trade fill representation."""
    fill_id: str
    order_id: str
    symbol: str
    quantity: int
    price: float
    commission: float
    fill_time: datetime


class OrderManager:
    """Manage order lifecycle and execution."""
    
    def __init__(self) -> None:
        self.orders: dict[str, Order] = {}
        self.fills: dict[str, list[Fill]] = {}
    
    def create_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: int,
        order_type: OrderType = OrderType.LIMIT,
        price: Optional[float] = None,
    ) -> Order:
        """
        Create a new order.
        
        Args:
            account_id: Account identifier
            symbol: Stock symbol
            side: BUY or SELL
            quantity: Order quantity
            order_type: Order type
            price: Limit price (required for LIMIT orders)
            
        Returns:
            Created order
        """
        order_id = f"ORD-{uuid4().hex[:12]}"
        
        order = Order(
            order_id=order_id,
            account_id=account_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=OrderStatus.PENDING,
        )
        
        self.orders[order_id] = order
        self.fills[order_id] = []
        
        return order
    
    def submit_order(self, order_id: str, broker_order_id: Optional[str] = None) -> bool:
        """
        Mark order as submitted to broker.
        
        Args:
            order_id: Order identifier
            broker_order_id: Broker's order identifier
            
        Returns:
            Success status
        """
        order = self.orders.get(order_id)
        if not order:
            return False
        
        order.status = OrderStatus.SUBMITTED
        order.broker_order_id = broker_order_id
        order.updated_at = datetime.now()
        
        return True
    
    def add_fill(
        self,
        order_id: str,
        quantity: int,
        price: float,
        commission: float = 0.0,
    ) -> Optional[Fill]:
        """
        Add a fill to an order.
        
        Args:
            order_id: Order identifier
            quantity: Filled quantity
            price: Fill price
            commission: Commission charged
            
        Returns:
            Fill object if successful
        """
        order = self.orders.get(order_id)
        if not order:
            return None
        
        fill_id = f"FILL-{uuid4().hex[:12]}"
        fill = Fill(
            fill_id=fill_id,
            order_id=order_id,
            symbol=order.symbol,
            quantity=quantity,
            price=price,
            commission=commission,
            fill_time=datetime.now(),
        )
        
        self.fills[order_id].append(fill)
        
        # Update order
        order.filled_quantity += quantity
        order.commission += commission
        
        # Recalculate average fill price
        total_value = sum(f.quantity * f.price for f in self.fills[order_id])
        order.filled_avg_price = total_value / order.filled_quantity
        
        # Update status
        if order.filled_quantity >= order.quantity:
            order.status = OrderStatus.FILLED
        elif order.filled_quantity > 0:
            order.status = OrderStatus.PARTIAL_FILLED
        
        order.updated_at = datetime.now()
        
        return fill
    
    def cancel_order(self, order_id: str, reason: Optional[str] = None) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order identifier
            reason: Cancellation reason
            
        Returns:
            Success status
        """
        order = self.orders.get(order_id)
        if not order:
            return False
        
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False
        
        order.status = OrderStatus.CANCELLED
        order.error_message = reason
        order.updated_at = datetime.now()
        
        return True
    
    def reject_order(self, order_id: str, reason: str) -> bool:
        """
        Reject an order.
        
        Args:
            order_id: Order identifier
            reason: Rejection reason
            
        Returns:
            Success status
        """
        order = self.orders.get(order_id)
        if not order:
            return False
        
        order.status = OrderStatus.REJECTED
        order.error_message = reason
        order.updated_at = datetime.now()
        
        return True
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self.orders.get(order_id)
    
    def get_fills(self, order_id: str) -> list[Fill]:
        """Get all fills for an order."""
        return self.fills.get(order_id, [])
    
    def get_active_orders(self, account_id: Optional[str] = None) -> list[Order]:
        """Get all active orders."""
        active_statuses = {
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIAL_FILLED,
        }
        
        orders = [
            order for order in self.orders.values()
            if order.status in active_statuses
        ]
        
        if account_id:
            orders = [o for o in orders if o.account_id == account_id]
        
        return orders
    
    def get_order_history(
        self,
        account_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> list[Order]:
        """Get order history with optional filters."""
        orders = list(self.orders.values())
        
        if account_id:
            orders = [o for o in orders if o.account_id == account_id]
        
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        
        return sorted(orders, key=lambda o: o.created_at, reverse=True)
