"""Risk engine for portfolio and order validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RiskRuleType(str, Enum):
    """Risk rule types."""
    SINGLE_STOCK_MAX_WEIGHT = "single_stock_max_weight"
    INDUSTRY_MAX_WEIGHT = "industry_max_weight"
    DAILY_MAX_TURNOVER = "daily_max_turnover"
    MAX_DRAWDOWN = "max_drawdown"
    LIQUIDITY_CHECK = "liquidity_check"
    HALT_CHECK = "halt_check"
    ST_CHECK = "st_check"
    LIMIT_PRICE_CHECK = "limit_price_check"
    # --- new rule types ---
    POSITION_STOP_LOSS = "position_stop_loss"      # individual position return trigger
    MAX_PORTFOLIO_DRAWDOWN = "max_portfolio_drawdown"  # portfolio peak-to-trough limit
    HIGH_VOLATILITY_BLOCK = "high_volatility_block"    # block buy when vol too high
    LEVERAGE_LIMIT = "leverage_limit"                  # total exposure / NAV cap


class RiskSeverity(str, Enum):
    """Risk severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class RiskDecision(str, Enum):
    """Risk decision outcomes."""
    ALLOW = "ALLOW"
    WARN = "WARN"
    DOWNGRADE = "DOWNGRADE"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class RiskRule:
    """Risk rule configuration."""
    rule_id: str
    rule_type: RiskRuleType
    scope: str  # "portfolio", "symbol", "industry"
    threshold: float
    action_on_breach: RiskDecision
    enabled: bool = True
    description: str = ""


@dataclass(frozen=True)
class RiskCheckResult:
    """Result of a risk check."""
    rule_id: str
    passed: bool
    severity: RiskSeverity
    decision: RiskDecision
    message: str
    details: Optional[dict[str, object]] = None


class RiskEngine:
    """Risk engine for validating orders and recommendations."""
    
    def __init__(self) -> None:
        self.rules: dict[str, RiskRule] = {}
        self._load_default_rules()
    
    def _load_default_rules(self) -> None:
        """Load default risk rules."""
        default_rules = [
            RiskRule(
                rule_id="single_stock_max_weight",
                rule_type=RiskRuleType.SINGLE_STOCK_MAX_WEIGHT,
                scope="symbol",
                threshold=0.30,
                action_on_breach=RiskDecision.BLOCK,
                description="Single stock cannot exceed 30% of portfolio",
            ),
            RiskRule(
                rule_id="industry_max_weight",
                rule_type=RiskRuleType.INDUSTRY_MAX_WEIGHT,
                scope="industry",
                threshold=0.40,
                action_on_breach=RiskDecision.WARN,
                description="Single industry should not exceed 40% of portfolio",
            ),
            RiskRule(
                rule_id="daily_max_turnover",
                rule_type=RiskRuleType.DAILY_MAX_TURNOVER,
                scope="portfolio",
                threshold=0.50,
                action_on_breach=RiskDecision.BLOCK,
                description="Daily turnover cannot exceed 50% of portfolio",
            ),
            RiskRule(
                rule_id="position_stop_loss",
                rule_type=RiskRuleType.POSITION_STOP_LOSS,
                scope="symbol",
                threshold=-0.08,   # -8% loss triggers forced-sell review
                action_on_breach=RiskDecision.BLOCK,
                description="Block adding to a position down more than 8%; force review",
            ),
            RiskRule(
                rule_id="max_portfolio_drawdown",
                rule_type=RiskRuleType.MAX_PORTFOLIO_DRAWDOWN,
                scope="portfolio",
                threshold=-0.15,   # -15% portfolio drawdown blocks new buys
                action_on_breach=RiskDecision.BLOCK,
                description="Block new purchases when portfolio drawdown exceeds 15%",
            ),
            RiskRule(
                rule_id="high_volatility_block",
                rule_type=RiskRuleType.HIGH_VOLATILITY_BLOCK,
                scope="symbol",
                threshold=0.04,    # 4% daily vol = extreme; warn at 0.03
                action_on_breach=RiskDecision.WARN,
                description="Warn when 20-day annualised daily volatility exceeds 4%",
            ),
            RiskRule(
                rule_id="leverage_limit",
                rule_type=RiskRuleType.LEVERAGE_LIMIT,
                scope="portfolio",
                threshold=1.0,     # no leverage by default
                action_on_breach=RiskDecision.BLOCK,
                description="Total exposure must not exceed NAV (no margin)",
            ),
        ]
        
        for rule in default_rules:
            self.rules[rule.rule_id] = rule
    
    def add_rule(self, rule: RiskRule) -> None:
        """Add or update a risk rule."""
        self.rules[rule.rule_id] = rule
    
    def remove_rule(self, rule_id: str) -> None:
        """Remove a risk rule."""
        self.rules.pop(rule_id, None)
    
    def check_single_stock_weight(
        self,
        symbol: str,
        target_weight: float,
        current_weight: float,
    ) -> RiskCheckResult:
        """Check if single stock weight is within limits."""
        rule = self.rules.get("single_stock_max_weight")
        if not rule or not rule.enabled:
            return RiskCheckResult(
                rule_id="single_stock_max_weight",
                passed=True,
                severity=RiskSeverity.INFO,
                decision=RiskDecision.ALLOW,
                message="Rule disabled or not found",
            )
        
        if target_weight > rule.threshold:
            return RiskCheckResult(
                rule_id=rule.rule_id,
                passed=False,
                severity=RiskSeverity.ERROR,
                decision=rule.action_on_breach,
                message=f"Target weight {target_weight:.2%} exceeds limit {rule.threshold:.2%}",
                details={
                    "symbol": symbol,
                    "target_weight": target_weight,
                    "threshold": rule.threshold,
                    "current_weight": current_weight,
                },
            )
        
        return RiskCheckResult(
            rule_id=rule.rule_id,
            passed=True,
            severity=RiskSeverity.INFO,
            decision=RiskDecision.ALLOW,
            message=f"Weight check passed: {target_weight:.2%} <= {rule.threshold:.2%}",
        )
    
    def check_daily_turnover(
        self,
        daily_turnover_ratio: float,
    ) -> RiskCheckResult:
        """Check if today's trading volume is within the daily turnover limit.

        Parameters
        ----------
        daily_turnover_ratio:
            Fraction of portfolio NAV already traded today (0–1).
        """
        rule = self.rules.get("daily_max_turnover")
        if not rule or not rule.enabled:
            return RiskCheckResult(
                rule_id="daily_max_turnover",
                passed=True,
                severity=RiskSeverity.INFO,
                decision=RiskDecision.ALLOW,
                message="Rule disabled or not found",
            )
        if daily_turnover_ratio > rule.threshold:
            return RiskCheckResult(
                rule_id=rule.rule_id,
                passed=False,
                severity=RiskSeverity.ERROR,
                decision=rule.action_on_breach,
                message=(
                    f"Daily turnover {daily_turnover_ratio:.2%} exceeds limit "
                    f"{rule.threshold:.2%}"
                ),
                details={"daily_turnover_ratio": daily_turnover_ratio, "threshold": rule.threshold},
            )
        return RiskCheckResult(
            rule_id=rule.rule_id,
            passed=True,
            severity=RiskSeverity.INFO,
            decision=RiskDecision.ALLOW,
            message=f"Daily turnover check passed: {daily_turnover_ratio:.2%}",
        )

    def check_position_stop_loss(
        self,
        symbol: str,
        position_return: float,
    ) -> RiskCheckResult:
        """Block adding to a losing position that has breached the stop-loss threshold.

        Parameters
        ----------
        symbol:
            Ticker being evaluated.
        position_return:
            Current unrealised return of this position (e.g. -0.10 = -10%).
        """
        rule = self.rules.get("position_stop_loss")
        if not rule or not rule.enabled:
            return RiskCheckResult(
                rule_id="position_stop_loss",
                passed=True,
                severity=RiskSeverity.INFO,
                decision=RiskDecision.ALLOW,
                message="Rule disabled or not found",
            )
        if position_return < rule.threshold:
            return RiskCheckResult(
                rule_id=rule.rule_id,
                passed=False,
                severity=RiskSeverity.CRITICAL,
                decision=rule.action_on_breach,
                message=(
                    f"{symbol} position return {position_return:.2%} breached "
                    f"stop-loss threshold {rule.threshold:.2%}"
                ),
                details={"symbol": symbol, "position_return": position_return, "threshold": rule.threshold},
            )
        return RiskCheckResult(
            rule_id=rule.rule_id,
            passed=True,
            severity=RiskSeverity.INFO,
            decision=RiskDecision.ALLOW,
            message=f"{symbol} within stop-loss limit: {position_return:.2%}",
        )

    def check_portfolio_drawdown(
        self,
        portfolio_drawdown: float,
    ) -> RiskCheckResult:
        """Block new buys when portfolio has fallen beyond the max-drawdown threshold.

        Parameters
        ----------
        portfolio_drawdown:
            Peak-to-trough return of the portfolio (negative, e.g. -0.12 = -12%).
        """
        rule = self.rules.get("max_portfolio_drawdown")
        if not rule or not rule.enabled:
            return RiskCheckResult(
                rule_id="max_portfolio_drawdown",
                passed=True,
                severity=RiskSeverity.INFO,
                decision=RiskDecision.ALLOW,
                message="Rule disabled or not found",
            )
        if portfolio_drawdown < rule.threshold:
            return RiskCheckResult(
                rule_id=rule.rule_id,
                passed=False,
                severity=RiskSeverity.CRITICAL,
                decision=rule.action_on_breach,
                message=(
                    f"Portfolio drawdown {portfolio_drawdown:.2%} exceeds limit "
                    f"{rule.threshold:.2%}"
                ),
                details={"portfolio_drawdown": portfolio_drawdown, "threshold": rule.threshold},
            )
        return RiskCheckResult(
            rule_id=rule.rule_id,
            passed=True,
            severity=RiskSeverity.INFO,
            decision=RiskDecision.ALLOW,
            message=f"Portfolio drawdown within limit: {portfolio_drawdown:.2%}",
        )

    def check_volatility(
        self,
        symbol: str,
        volatility_20d: float,
    ) -> RiskCheckResult:
        """Warn when a stock's recent daily volatility is unusually high.

        Parameters
        ----------
        volatility_20d:
            20-day realised daily volatility (e.g. 0.025 = 2.5% per day).
        """
        rule = self.rules.get("high_volatility_block")
        if not rule or not rule.enabled:
            return RiskCheckResult(
                rule_id="high_volatility_block",
                passed=True,
                severity=RiskSeverity.INFO,
                decision=RiskDecision.ALLOW,
                message="Rule disabled or not found",
            )
        if volatility_20d > rule.threshold:
            return RiskCheckResult(
                rule_id=rule.rule_id,
                passed=False,
                severity=RiskSeverity.WARNING,
                decision=rule.action_on_breach,
                message=(
                    f"{symbol} 20d volatility {volatility_20d:.2%} exceeds threshold "
                    f"{rule.threshold:.2%}"
                ),
                details={"symbol": symbol, "volatility_20d": volatility_20d, "threshold": rule.threshold},
            )
        return RiskCheckResult(
            rule_id=rule.rule_id,
            passed=True,
            severity=RiskSeverity.INFO,
            decision=RiskDecision.ALLOW,
            message=f"{symbol} volatility within acceptable range: {volatility_20d:.2%}",
        )

    def check_leverage(
        self,
        leverage_ratio: float,
    ) -> RiskCheckResult:
        """Ensure the portfolio is not using margin beyond the configured limit.

        Parameters
        ----------
        leverage_ratio:
            Total gross exposure / NAV.  1.0 = fully invested, no margin.
        """
        rule = self.rules.get("leverage_limit")
        if not rule or not rule.enabled:
            return RiskCheckResult(
                rule_id="leverage_limit",
                passed=True,
                severity=RiskSeverity.INFO,
                decision=RiskDecision.ALLOW,
                message="Rule disabled or not found",
            )
        if leverage_ratio > rule.threshold:
            return RiskCheckResult(
                rule_id=rule.rule_id,
                passed=False,
                severity=RiskSeverity.ERROR,
                decision=rule.action_on_breach,
                message=(
                    f"Leverage ratio {leverage_ratio:.2f}x exceeds limit {rule.threshold:.2f}x"
                ),
                details={"leverage_ratio": leverage_ratio, "threshold": rule.threshold},
            )
        return RiskCheckResult(
            rule_id=rule.rule_id,
            passed=True,
            severity=RiskSeverity.INFO,
            decision=RiskDecision.ALLOW,
            message=f"Leverage within limit: {leverage_ratio:.2f}x",
        )

    def check_industry_concentration(
        self,
        industry: str,
        target_weight: float,
    ) -> RiskCheckResult:
        """Check if industry concentration is within limits."""
        rule = self.rules.get("industry_max_weight")
        if not rule or not rule.enabled:
            return RiskCheckResult(
                rule_id="industry_max_weight",
                passed=True,
                severity=RiskSeverity.INFO,
                decision=RiskDecision.ALLOW,
                message="Rule disabled or not found",
            )
        
        if target_weight > rule.threshold:
            return RiskCheckResult(
                rule_id=rule.rule_id,
                passed=False,
                severity=RiskSeverity.WARNING,
                decision=rule.action_on_breach,
                message=f"Industry {industry} weight {target_weight:.2%} exceeds limit {rule.threshold:.2%}",
                details={
                    "industry": industry,
                    "target_weight": target_weight,
                    "threshold": rule.threshold,
                },
            )
        
        return RiskCheckResult(
            rule_id=rule.rule_id,
            passed=True,
            severity=RiskSeverity.INFO,
            decision=RiskDecision.ALLOW,
            message=f"Industry concentration check passed",
        )
    
    def validate_recommendation(
        self,
        symbol: str,
        action: str,
        target_weight: float,
        current_weight: float,
        industry: str,
        industry_weight: float,
        *,
        position_return: Optional[float] = None,
        portfolio_drawdown: Optional[float] = None,
        volatility_20d: Optional[float] = None,
        leverage_ratio: Optional[float] = None,
        daily_turnover_ratio: Optional[float] = None,
    ) -> list[RiskCheckResult]:
        """Validate a recommendation against all applicable rules.

        Keyword-only parameters are optional: pass them when the data is
        available to unlock the corresponding guards.
        """
        results: list[RiskCheckResult] = []

        # Portfolio-level guards (block all new buys)
        if portfolio_drawdown is not None and action == "BUY":
            results.append(self.check_portfolio_drawdown(portfolio_drawdown))

        if leverage_ratio is not None and action == "BUY":
            results.append(self.check_leverage(leverage_ratio))

        if daily_turnover_ratio is not None and action == "BUY":
            results.append(self.check_daily_turnover(daily_turnover_ratio))

        # Symbol-level guards
        if action in ("BUY", "HOLD"):
            results.append(
                self.check_single_stock_weight(symbol, target_weight, current_weight)
            )
            results.append(
                self.check_industry_concentration(industry, industry_weight)
            )

        if action == "BUY" and position_return is not None:
            results.append(self.check_position_stop_loss(symbol, position_return))

        if volatility_20d is not None:
            results.append(self.check_volatility(symbol, volatility_20d))

        return results
    
    def get_final_decision(self, results: list[RiskCheckResult]) -> RiskDecision:
        """Get final decision from multiple risk check results."""
        if not results:
            return RiskDecision.ALLOW
        
        # If any check blocks, block the entire recommendation
        if any(r.decision == RiskDecision.BLOCK for r in results):
            return RiskDecision.BLOCK
        
        # If any check downgrades, downgrade the recommendation
        if any(r.decision == RiskDecision.DOWNGRADE for r in results):
            return RiskDecision.DOWNGRADE
        
        # If any check warns, warn but allow
        if any(r.decision == RiskDecision.WARN for r in results):
            return RiskDecision.WARN
        
        return RiskDecision.ALLOW
