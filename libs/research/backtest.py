"""Backtesting framework for strategy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Optional

from libs.quant_core.models import MarketBar


@dataclass(frozen=True)
class BacktestConfig:
    """Backtest configuration."""
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003  # 0.03%
    slippage_rate: float = 0.0001  # 0.01%
    min_commission: float = 5.0
    
    # Position sizing
    max_position_size: float = 0.15  # 15% max per position
    max_positions: int = 10
    
    # Risk management
    stop_loss_pct: Optional[float] = None  # e.g., 0.1 for 10% stop loss
    take_profit_pct: Optional[float] = None


@dataclass
class Trade:
    """Trade record."""
    trade_id: str
    symbol: str
    entry_date: date
    entry_price: float
    quantity: int
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    commission: float = 0.0
    reason: str = ""


@dataclass
class BacktestMetrics:
    """Backtest performance metrics."""
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    max_win: float
    max_loss: float


class Backtest:
    """Backtesting engine."""
    
    def __init__(self, config: Optional[BacktestConfig] = None) -> None:
        self.config = config or BacktestConfig()
        self.reset()
    
    def reset(self) -> None:
        """Reset backtest state."""
        self.cash = self.config.initial_capital
        self.positions: dict[str, Trade] = {}
        self.closed_trades: list[Trade] = []
        self.equity_curve: list[tuple[date, float]] = []
        self.current_date: Optional[date] = None
    
    def calculate_commission(self, value: float) -> float:
        """Calculate trading commission."""
        commission = value * self.config.commission_rate
        return max(commission, self.config.min_commission)
    
    def calculate_slippage(self, price: float, quantity: int) -> float:
        """Calculate slippage cost."""
        return price * quantity * self.config.slippage_rate
    
    def can_open_position(self, symbol: str, price: float, quantity: int) -> bool:
        """Check if can open a new position."""
        # Check max positions
        if len(self.positions) >= self.config.max_positions:
            return False
        
        # Check if already have position
        if symbol in self.positions:
            return False
        
        # Check position size — value existing positions at their entry_price
        # (we don't have a marked-to-market price for *other* held symbols here).
        position_value = price * quantity
        existing_prices = {sym: tr.entry_price for sym, tr in self.positions.items()}
        existing_prices[symbol] = price
        total_value = self.get_total_value(existing_prices)
        position_pct = position_value / total_value if total_value > 0 else 1.0
        
        if position_pct > self.config.max_position_size:
            return False
        
        # Check cash
        cost = position_value + self.calculate_commission(position_value)
        if cost > self.cash:
            return False
        
        return True
    
    def open_position(
        self,
        symbol: str,
        price: float,
        quantity: int,
        trade_date: date,
        reason: str = "",
    ) -> Optional[Trade]:
        """Open a new position."""
        if not self.can_open_position(symbol, price, quantity):
            return None
        
        position_value = price * quantity
        commission = self.calculate_commission(position_value)
        slippage = self.calculate_slippage(price, quantity)
        
        total_cost = position_value + commission + slippage
        
        trade = Trade(
            trade_id=f"T{len(self.closed_trades) + len(self.positions) + 1:04d}",
            symbol=symbol,
            entry_date=trade_date,
            entry_price=price,
            quantity=quantity,
            commission=commission,
            reason=reason,
        )
        
        self.positions[symbol] = trade
        self.cash -= total_cost
        
        return trade
    
    def close_position(
        self,
        symbol: str,
        price: float,
        trade_date: date,
        reason: str = "",
    ) -> Optional[Trade]:
        """Close an existing position."""
        if symbol not in self.positions:
            return None
        
        trade = self.positions[symbol]
        
        position_value = price * trade.quantity
        commission = self.calculate_commission(position_value)
        slippage = self.calculate_slippage(price, trade.quantity)
        
        proceeds = position_value - commission - slippage
        
        # Calculate P&L
        cost = trade.entry_price * trade.quantity
        trade.pnl = proceeds - cost - trade.commission
        trade.pnl_pct = trade.pnl / cost
        trade.exit_date = trade_date
        trade.exit_price = price
        trade.commission += commission
        trade.reason = reason
        
        self.cash += proceeds
        self.closed_trades.append(trade)
        del self.positions[symbol]
        
        return trade
    
    def get_total_value(self, current_prices: dict[str, float]) -> float:
        """Calculate total portfolio value."""
        position_value = sum(
            current_prices.get(symbol, trade.entry_price) * trade.quantity
            for symbol, trade in self.positions.items()
        )
        return self.cash + position_value
    
    def update_equity_curve(self, trade_date: date, current_prices: dict[str, float]) -> None:
        """Update equity curve."""
        total_value = self.get_total_value(current_prices)
        self.equity_curve.append((trade_date, total_value))
        self.current_date = trade_date
    
    def run(
        self,
        data: dict[str, list[MarketBar]],  # symbol -> bars
        strategy: Callable[[date, dict[str, MarketBar]], list[tuple[str, str]]],  # returns [(symbol, action)]
    ) -> BacktestMetrics:
        """
        Run backtest.
        
        Args:
            data: Historical market data
            strategy: Strategy function that returns trading signals
            
        Returns:
            Backtest metrics
        """
        self.reset()
        
        # Get all trading dates
        all_dates = set()
        for bars in data.values():
            all_dates.update(bar.trade_date for bar in bars)
        
        trading_dates = sorted(all_dates)
        
        # Run backtest day by day
        for trade_date in trading_dates:
            # Get current day data
            current_data = {}
            current_prices = {}
            
            for symbol, bars in data.items():
                for bar in bars:
                    if bar.trade_date == trade_date:
                        current_data[symbol] = bar
                        current_prices[symbol] = bar.close
                        break
            
            # Get strategy signals
            signals = strategy(trade_date, current_data)
            
            # Execute signals
            for symbol, action in signals:
                if action == "BUY" and symbol in current_prices:
                    price = current_prices[symbol]
                    # Calculate position size
                    position_value = self.get_total_value(current_prices) * 0.1  # 10% per position
                    quantity = int(position_value / price / 100) * 100  # Round to 100 shares
                    
                    if quantity > 0:
                        self.open_position(symbol, price, quantity, trade_date, "Strategy signal")
                
                elif action == "SELL" and symbol in self.positions:
                    price = current_prices[symbol]
                    self.close_position(symbol, price, trade_date, "Strategy signal")
            
            # Check stop loss and take profit
            for symbol in list(self.positions.keys()):
                if symbol not in current_prices:
                    continue
                
                trade = self.positions[symbol]
                current_price = current_prices[symbol]
                pnl_pct = (current_price - trade.entry_price) / trade.entry_price
                
                # Stop loss
                if self.config.stop_loss_pct and pnl_pct <= -self.config.stop_loss_pct:
                    self.close_position(symbol, current_price, trade_date, "Stop loss")
                
                # Take profit
                elif self.config.take_profit_pct and pnl_pct >= self.config.take_profit_pct:
                    self.close_position(symbol, current_price, trade_date, "Take profit")
            
            # Update equity curve
            self.update_equity_curve(trade_date, current_prices)
        
        # Close all remaining positions
        if self.equity_curve:
            final_date = self.equity_curve[-1][0]
            final_prices = {}
            for symbol, bars in data.items():
                for bar in reversed(bars):
                    if bar.trade_date <= final_date:
                        final_prices[symbol] = bar.close
                        break
            
            for symbol in list(self.positions.keys()):
                if symbol in final_prices:
                    self.close_position(symbol, final_prices[symbol], final_date, "End of backtest")
        
        # Calculate metrics
        return self.calculate_metrics()
    
    def calculate_metrics(self) -> BacktestMetrics:
        """Calculate backtest performance metrics."""
        if not self.equity_curve:
            return BacktestMetrics(
                total_return=0.0,
                annual_return=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                avg_win=0.0,
                avg_loss=0.0,
                max_win=0.0,
                max_loss=0.0,
            )
        
        # Total return
        initial_value = self.config.initial_capital
        final_value = self.equity_curve[-1][1]
        total_return = (final_value - initial_value) / initial_value
        
        # Annual return
        days = (self.equity_curve[-1][0] - self.equity_curve[0][0]).days
        years = days / 365.25
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0
        
        # Sharpe ratio (simplified)
        returns = []
        for i in range(1, len(self.equity_curve)):
            prev_value = self.equity_curve[i-1][1]
            curr_value = self.equity_curve[i][1]
            daily_return = (curr_value - prev_value) / prev_value
            returns.append(daily_return)
        
        if returns:
            avg_return = sum(returns) / len(returns)
            std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe_ratio = (avg_return / std_return) * (252 ** 0.5) if std_return > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        # Max drawdown
        peak = initial_value
        max_dd = 0.0
        for _, value in self.equity_curve:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
        
        # Trade statistics
        winning_trades = [t for t in self.closed_trades if t.pnl > 0]
        losing_trades = [t for t in self.closed_trades if t.pnl < 0]
        
        total_trades = len(self.closed_trades)
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0
        
        total_wins = sum(t.pnl for t in winning_trades)
        total_losses = abs(sum(t.pnl for t in losing_trades))
        profit_factor = total_wins / total_losses if total_losses > 0 else 0.0
        
        avg_win = total_wins / len(winning_trades) if winning_trades else 0.0
        avg_loss = -total_losses / len(losing_trades) if losing_trades else 0.0
        
        max_win = max((t.pnl for t in winning_trades), default=0.0)
        max_loss = min((t.pnl for t in losing_trades), default=0.0)
        
        return BacktestMetrics(
            total_return=total_return,
            annual_return=annual_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_dd,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=total_trades,
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            avg_win=avg_win,
            avg_loss=avg_loss,
            max_win=max_win,
            max_loss=max_loss,
        )
