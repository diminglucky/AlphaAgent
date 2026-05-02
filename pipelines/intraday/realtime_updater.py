"""Real-time intraday data update pipeline."""

import logging
import time
from datetime import datetime
from typing import Callable, Optional

from libs.market_data.providers import MarketDataProvider
from libs.quant_core.models import RealtimeQuote


logger = logging.getLogger(__name__)


class RealtimeUpdater:
    """Real-time market data updater for intraday trading."""
    
    def __init__(
        self,
        provider: MarketDataProvider,
        update_interval: int = 3,  # seconds
    ) -> None:
        """
        Initialize real-time updater.
        
        Args:
            provider: Market data provider
            update_interval: Update interval in seconds
        """
        self.provider = provider
        self.update_interval = update_interval
        self.is_running = False
        self.watchlist: list[str] = []
        self.callbacks: list[Callable[[list[RealtimeQuote]], None]] = []
    
    def add_symbols(self, symbols: list[str]) -> None:
        """Add symbols to watchlist."""
        for symbol in symbols:
            if symbol not in self.watchlist:
                self.watchlist.append(symbol)
        logger.info(f"Watchlist updated: {len(self.watchlist)} symbols")
    
    def remove_symbols(self, symbols: list[str]) -> None:
        """Remove symbols from watchlist."""
        for symbol in symbols:
            if symbol in self.watchlist:
                self.watchlist.remove(symbol)
        logger.info(f"Watchlist updated: {len(self.watchlist)} symbols")
    
    def register_callback(self, callback: Callable[[list[RealtimeQuote]], None]) -> None:
        """Register a callback for quote updates."""
        self.callbacks.append(callback)
    
    def start(self) -> None:
        """Start real-time updates."""
        if self.is_running:
            logger.warning("Updater is already running")
            return
        
        self.is_running = True
        logger.info("Starting real-time updater")
        
        try:
            while self.is_running:
                if not self.watchlist:
                    logger.debug("Watchlist is empty, waiting...")
                    time.sleep(self.update_interval)
                    continue
                
                try:
                    # Fetch quotes
                    quotes = self.provider.get_realtime_quotes(self.watchlist)
                    
                    if quotes:
                        logger.debug(f"Fetched {len(quotes)} quotes")
                        
                        # Notify callbacks
                        for callback in self.callbacks:
                            try:
                                callback(quotes)
                            except Exception as e:
                                logger.error(f"Callback error: {e}")
                    
                except Exception as e:
                    logger.error(f"Failed to fetch quotes: {e}")
                
                # Wait for next update
                time.sleep(self.update_interval)
        
        finally:
            self.is_running = False
            logger.info("Real-time updater stopped")
    
    def stop(self) -> None:
        """Stop real-time updates."""
        logger.info("Stopping real-time updater")
        self.is_running = False
    
    def get_latest_quotes(self) -> list[RealtimeQuote]:
        """Get latest quotes for watchlist (one-time fetch)."""
        if not self.watchlist:
            return []
        
        try:
            return self.provider.get_realtime_quotes(self.watchlist)
        except Exception as e:
            logger.error(f"Failed to fetch quotes: {e}")
            return []


class TradingSessionManager:
    """Manage trading session timing."""
    
    # A股交易时间
    MORNING_START = (9, 30)
    MORNING_END = (11, 30)
    AFTERNOON_START = (13, 0)
    AFTERNOON_END = (15, 0)
    
    @staticmethod
    def is_trading_time(dt: Optional[datetime] = None) -> bool:
        """Check if current time is within trading hours."""
        if dt is None:
            dt = datetime.now()
        
        # Check weekday (Monday=0, Sunday=6)
        if dt.weekday() >= 5:  # Weekend
            return False
        
        current_time = (dt.hour, dt.minute)
        
        # Morning session
        if TradingSessionManager.MORNING_START <= current_time < TradingSessionManager.MORNING_END:
            return True
        
        # Afternoon session
        if TradingSessionManager.AFTERNOON_START <= current_time < TradingSessionManager.AFTERNOON_END:
            return True
        
        return False
    
    @staticmethod
    def get_session_status(dt: Optional[datetime] = None) -> str:
        """Get current session status."""
        if dt is None:
            dt = datetime.now()
        
        if dt.weekday() >= 5:
            return "WEEKEND"
        
        current_time = (dt.hour, dt.minute)
        
        if current_time < TradingSessionManager.MORNING_START:
            return "PRE_MARKET"
        elif TradingSessionManager.MORNING_START <= current_time < TradingSessionManager.MORNING_END:
            return "MORNING_SESSION"
        elif TradingSessionManager.MORNING_END <= current_time < TradingSessionManager.AFTERNOON_START:
            return "LUNCH_BREAK"
        elif TradingSessionManager.AFTERNOON_START <= current_time < TradingSessionManager.AFTERNOON_END:
            return "AFTERNOON_SESSION"
        else:
            return "AFTER_MARKET"
