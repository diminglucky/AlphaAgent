"""Daily bar data backfill pipeline."""

import logging
from datetime import date, timedelta

from libs.market_data.providers import MarketDataProvider
from libs.quant_core.models import Instrument, MarketBar


logger = logging.getLogger(__name__)


class DailyBarBackfillPipeline:
    """Pipeline for backfilling historical daily bar data."""
    
    def __init__(self, provider: MarketDataProvider) -> None:
        self.provider = provider
    
    def backfill_symbol(
        self,
        symbol: str,
        start_date: date,
        end_date: date | None = None,
    ) -> list[MarketBar]:
        """Backfill daily bars for a single symbol."""
        if end_date is None:
            end_date = date.today()
        
        logger.info(f"Backfilling {symbol} from {start_date} to {end_date}")
        
        try:
            bars = self.provider.get_bars(
                symbol=symbol,
                freq="1d",
                start=start_date,
                end=end_date,
            )
            logger.info(f"Retrieved {len(bars)} bars for {symbol}")
            return bars
        except Exception as exc:
            logger.error(f"Failed to backfill {symbol}: {exc}")
            return []
    
    def backfill_all_instruments(
        self,
        instruments: list[Instrument],
        start_date: date,
        end_date: date | None = None,
        batch_size: int = 10,
    ) -> dict[str, list[MarketBar]]:
        """Backfill daily bars for all instruments."""
        results: dict[str, list[MarketBar]] = {}
        
        logger.info(f"Starting backfill for {len(instruments)} instruments")
        
        for i, instrument in enumerate(instruments):
            if i > 0 and i % batch_size == 0:
                logger.info(f"Progress: {i}/{len(instruments)} instruments processed")
            
            bars = self.backfill_symbol(
                symbol=instrument.symbol,
                start_date=start_date,
                end_date=end_date,
            )
            
            if bars:
                results[instrument.symbol] = bars
        
        logger.info(f"Backfill complete: {len(results)} symbols with data")
        return results
    
    def incremental_update(
        self,
        symbols: list[str],
        lookback_days: int = 5,
    ) -> dict[str, list[MarketBar]]:
        """Perform incremental update for recent trading days."""
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)
        
        logger.info(f"Incremental update for {len(symbols)} symbols, lookback={lookback_days} days")
        
        results: dict[str, list[MarketBar]] = {}
        
        for symbol in symbols:
            bars = self.backfill_symbol(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
            
            if bars:
                results[symbol] = bars
        
        return results
