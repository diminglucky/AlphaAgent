"""Enhanced recommendation service with signal and risk integration."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from apps.api.app.core.config import get_settings
from apps.api.app.db.bootstrap import ensure_database_initialized
from apps.api.app.db.repositories import PortfolioRepository, RecommendationRepository
from apps.api.app.db.session import session_scope
from apps.api.app.services.market_service import MarketService
from libs.features.technical import build_technical_features
from libs.portfolio.optimizer import PortfolioOptimizer
from libs.quant_core.enums import RecommendationAction
from libs.quant_core.models import Recommendation
from libs.recommendations.signal_engine import SignalEngine
from libs.risk.engine import RiskDecision, RiskEngine


class EnhancedRecommendationService:
    """Enhanced recommendation service with full pipeline."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self.market_service = MarketService()
        self.signal_engine = SignalEngine()
        self.risk_engine = RiskEngine()
        self.portfolio_optimizer = PortfolioOptimizer()
    
    def generate_recommendations(
        self,
        symbols: list[str],
        lookback_days: int = 60,
    ) -> list[Recommendation]:
        """
        Generate recommendations for given symbols.
        
        Args:
            symbols: List of symbols to analyze
            lookback_days: Number of days of historical data to use
            
        Returns:
            List of recommendations
        """
        ensure_database_initialized()
        
        recommendations = []
        end_date = date.today()
        start_date = date.fromordinal(end_date.toordinal() - lookback_days)
        
        # Get portfolio context
        with session_scope() as session:
            portfolio_repo = PortfolioRepository(session)
            portfolio_summary = portfolio_repo.get_summary()
            positions = portfolio_repo.list_positions()
        
        if not portfolio_summary:
            return []
        
        # Calculate current weights
        current_weights = {}
        industry_weights = {}
        
        for pos in positions:
            weight = pos.market_value / portfolio_summary.total_asset
            current_weights[pos.symbol] = weight
            
            # Simplified industry mapping
            industry = self._get_industry(pos.symbol)
            industry_weights[industry] = industry_weights.get(industry, 0.0) + weight
        
        # Generate signals for each symbol
        for symbol in symbols:
            try:
                # Get historical data
                bars = self.market_service.get_bars(
                    symbol=symbol,
                    freq="1d",
                    start=start_date,
                    end=end_date,
                )
                
                if not bars or len(bars) < 20:
                    continue
                
                # Build technical features
                bar_tuples = [
                    (bar.trade_date, bar.close, bar.volume, bar.turnover_rate)
                    for bar in bars
                ]
                features = build_technical_features(symbol, bar_tuples)
                
                if not features:
                    continue
                
                # Generate signal
                signal = self.signal_engine.generate_signal(features)
                action = self.signal_engine.signal_to_action(signal)
                
                # Skip HOLD signals
                if action == RecommendationAction.HOLD:
                    continue
                
                # Calculate target weight
                current_weight = current_weights.get(symbol, 0.0)
                
                if action == RecommendationAction.BUY:
                    # Suggest 10% position for new buys
                    target_weight = 0.10 if current_weight == 0 else current_weight * 1.2
                    target_weight = min(target_weight, 0.30)  # Cap at 30%
                else:  # SELL
                    target_weight = current_weight * 0.5  # Reduce by half
                
                # Risk checks
                industry = self._get_industry(symbol)
                industry_weight = industry_weights.get(industry, 0.0)
                
                if action == RecommendationAction.BUY:
                    # Adjust industry weight for new position
                    new_industry_weight = industry_weight + (target_weight - current_weight)
                else:
                    new_industry_weight = industry_weight
                
                risk_results = self.risk_engine.validate_recommendation(
                    symbol=symbol,
                    action=action.value,
                    target_weight=target_weight,
                    current_weight=current_weight,
                    industry=industry,
                    industry_weight=new_industry_weight,
                )
                
                final_decision = self.risk_engine.get_final_decision(risk_results)
                
                # Determine status based on risk decision
                if final_decision == RiskDecision.BLOCK:
                    status = "BLOCKED"
                elif final_decision == RiskDecision.WARN:
                    status = "READY"
                else:
                    status = "READY"
                
                # Extract risk flags
                risk_flags = []
                for result in risk_results:
                    if not result.passed:
                        risk_flags.append(result.rule_id)
                
                # Build reason summary
                reason_parts = []
                reason_parts.append(f"信号得分: {signal.raw_score:.3f}")
                reason_parts.append(f"置信度: {signal.confidence:.2%}")
                
                if signal.components.get("momentum", 0) > 0.3:
                    reason_parts.append("动量强劲")
                if signal.components.get("trend", 0) > 0.3:
                    reason_parts.append("趋势向上")
                if signal.components.get("volume", 0) > 0.3:
                    reason_parts.append("成交量配合")
                
                reason_summary = "；".join(reason_parts)
                
                # Create recommendation
                rec = Recommendation(
                    recommendation_id=f"REC-{symbol}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    symbol=symbol,
                    action=action.value,
                    target_weight=target_weight,
                    confidence=signal.confidence,
                    time_horizon="swing_5d",
                    reason_summary=reason_summary,
                    risk_flags=risk_flags,
                    status=status,
                    created_at=datetime.now(),
                )
                
                recommendations.append(rec)
            
            except Exception as e:
                print(f"Error generating recommendation for {symbol}: {e}")
                continue
        
        return recommendations
    
    def _get_industry(self, symbol: str) -> str:
        """Get industry for symbol (simplified mapping)."""
        # Simplified industry mapping
        industry_map = {
            "600519.SH": "白酒",
            "000001.SZ": "银行",
            "300750.SZ": "电池",
        }
        return industry_map.get(symbol, "未知")
    
    def generate_and_save_recommendations(
        self,
        symbols: list[str],
    ) -> int:
        """
        Generate recommendations and save to database.
        
        Args:
            symbols: List of symbols to analyze
            
        Returns:
            Number of recommendations generated
        """
        recommendations = self.generate_recommendations(symbols)
        
        if not recommendations:
            return 0
        
        # Save to database
        ensure_database_initialized()
        with session_scope() as session:
            from apps.api.app.db.models import RecommendationORM
            
            for rec in recommendations:
                orm_rec = RecommendationORM(
                    recommendation_id=rec.recommendation_id,
                    symbol=rec.symbol,
                    action=rec.action,
                    target_weight=rec.target_weight,
                    confidence=rec.confidence,
                    time_horizon=rec.time_horizon,
                    reason_summary=rec.reason_summary,
                    risk_flags=rec.risk_flags,
                    status=rec.status,
                    created_at=rec.created_at,
                )
                session.merge(orm_rec)
        
        return len(recommendations)
