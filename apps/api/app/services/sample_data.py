from datetime import date, datetime

from libs.quant_core.enums import (
    OrderSide,
    RecommendationAction,
    RecommendationStatus,
    RiskFlag,
)
from libs.quant_core.models import (
    Instrument,
    MarketBar,
    PortfolioSummary,
    Position,
    Recommendation,
    RealtimeQuote,
)


NOW = datetime(2026, 4, 25, 10, 35, 0)

INSTRUMENTS = [
    Instrument(
        symbol="600519.SH",
        exchange="SH",
        name="贵州茅台",
        industry="白酒",
        list_date=date(2001, 8, 27),
        delist_date=None,
        status="listed",
        is_st=False,
    ),
    Instrument(
        symbol="000001.SZ",
        exchange="SZ",
        name="平安银行",
        industry="银行",
        list_date=date(1991, 4, 3),
        delist_date=None,
        status="listed",
        is_st=False,
    ),
    Instrument(
        symbol="300750.SZ",
        exchange="SZ",
        name="宁德时代",
        industry="电池",
        list_date=date(2018, 6, 11),
        delist_date=None,
        status="listed",
        is_st=False,
    ),
]

DAILY_BARS = {
    "600519.SH": [
        MarketBar(
            symbol="600519.SH",
            trade_date=date(2026, 4, 23),
            open=1698.0,
            high=1715.0,
            low=1691.2,
            close=1708.8,
            volume=30210,
            amount=51500000.0,
            turnover_rate=0.21,
            adj_type="qfq",
            data_source="mock",
        ),
        MarketBar(
            symbol="600519.SH",
            trade_date=date(2026, 4, 24),
            open=1709.0,
            high=1720.5,
            low=1702.4,
            close=1717.3,
            volume=29876,
            amount=51280000.0,
            turnover_rate=0.20,
            adj_type="qfq",
            data_source="mock",
        ),
    ],
    "000001.SZ": [
        MarketBar(
            symbol="000001.SZ",
            trade_date=date(2026, 4, 23),
            open=11.2,
            high=11.35,
            low=11.12,
            close=11.29,
            volume=1452300,
            amount=16350000.0,
            turnover_rate=0.71,
            adj_type="qfq",
            data_source="mock",
        ),
        MarketBar(
            symbol="000001.SZ",
            trade_date=date(2026, 4, 24),
            open=11.30,
            high=11.46,
            low=11.25,
            close=11.40,
            volume=1584000,
            amount=18090000.0,
            turnover_rate=0.77,
            adj_type="qfq",
            data_source="mock",
        ),
    ],
    "300750.SZ": [
        MarketBar(
            symbol="300750.SZ",
            trade_date=date(2026, 4, 23),
            open=228.0,
            high=231.5,
            low=224.2,
            close=229.4,
            volume=214560,
            amount=49210000.0,
            turnover_rate=0.63,
            adj_type="qfq",
            data_source="mock",
        ),
        MarketBar(
            symbol="300750.SZ",
            trade_date=date(2026, 4, 24),
            open=229.8,
            high=235.1,
            low=228.3,
            close=234.2,
            volume=239870,
            amount=55530000.0,
            turnover_rate=0.70,
            adj_type="qfq",
            data_source="mock",
        ),
    ],
}

REALTIME_QUOTES = {
    "600519.SH": RealtimeQuote(
        symbol="600519.SH",
        quote_time=NOW,
        last_price=1719.5,
        bid1=1719.0,
        ask1=1719.6,
        volume=31220,
        turnover=53600000.0,
        pct_change=0.13,
        limit_up=1889.03,
        limit_down=1545.57,
    ),
    "000001.SZ": RealtimeQuote(
        symbol="000001.SZ",
        quote_time=NOW,
        last_price=11.38,
        bid1=11.37,
        ask1=11.38,
        volume=1610000,
        turnover=18340000.0,
        pct_change=-0.18,
        limit_up=12.54,
        limit_down=10.26,
    ),
    "300750.SZ": RealtimeQuote(
        symbol="300750.SZ",
        quote_time=NOW,
        last_price=236.8,
        bid1=236.5,
        ask1=236.8,
        volume=245000,
        turnover=57880000.0,
        pct_change=1.11,
        limit_up=257.62,
        limit_down=210.78,
    ),
}

PORTFOLIO_SUMMARY = PortfolioSummary(
    account_id="acct-demo-001",
    portfolio_name="主策略账户",
    base_currency="CNY",
    total_asset=1_000_000.0,
    cash=320_000.0,
    market_value=680_000.0,
    daily_pnl=8_520.5,
    total_pnl=96_200.0,
    updated_at=NOW,
)

POSITIONS = [
    Position(
        position_id="pos-600519",
        account_id="acct-demo-001",
        symbol="600519.SH",
        quantity=300,
        available_quantity=300,
        avg_cost=1640.0,
        market_value=515_850.0,
        unrealized_pnl=23_850.0,
        realized_pnl=0.0,
        updated_at=NOW,
    ),
    Position(
        position_id="pos-000001",
        account_id="acct-demo-001",
        symbol="000001.SZ",
        quantity=14_400,
        available_quantity=14_400,
        avg_cost=11.20,
        market_value=163_872.0,
        unrealized_pnl=2_592.0,
        realized_pnl=1_850.0,
        updated_at=NOW,
    ),
]

RECOMMENDATIONS = [
    Recommendation(
        recommendation_id="rec-300750-buy",
        symbol="300750.SZ",
        action=RecommendationAction.BUY.value,
        target_weight=0.10,
        confidence=0.78,
        time_horizon="swing_5d",
        reason_summary="动量延续，新能源板块强于市场，新闻面未见显著负面，当前组合对电池赛道暴露较低。",
        risk_flags=[RiskFlag.HIGH_VOLATILITY.value],
        status=RecommendationStatus.READY.value,
        created_at=NOW,
    ),
    Recommendation(
        recommendation_id="rec-600519-hold",
        symbol="600519.SH",
        action=RecommendationAction.HOLD.value,
        target_weight=0.52,
        confidence=0.66,
        time_horizon="position_trade",
        reason_summary="趋势仍强，但当前组合对白酒权重已偏高，不建议继续追高加仓。",
        risk_flags=[RiskFlag.CONCENTRATION.value],
        status=RecommendationStatus.READY.value,
        created_at=NOW,
    ),
    Recommendation(
        recommendation_id="rec-000001-sell",
        symbol="000001.SZ",
        action=RecommendationAction.SELL.value,
        target_weight=0.10,
        confidence=0.61,
        time_horizon="rebalance",
        reason_summary="基本面稳定但弹性有限，组合需要腾挪资金给更高赔率标的。",
        risk_flags=[],
        status=RecommendationStatus.READY.value,
        created_at=NOW,
    ),
]

EXPLANATIONS = {
    "300750.SZ": {
        "symbol": "300750.SZ",
        "summary": "当前建议偏买入，核心依据是趋势延续、板块强度提升和组合暴露可承受。",
        "drivers": [
            "近两个交易日价格强于板块均值。",
            "新能源链条新闻面偏正向，没有明显监管或业绩风险。",
            "当前组合未对电池行业形成过度集中。",
        ],
        "risk_notes": [
            "创业板高波动，盘中回撤可能放大。",
            "若指数转弱，建议重新评估仓位节奏。",
        ],
        "sources": ["mock:daily_bar", "mock:news_event", "mock:portfolio_context"],
    },
    "600519.SH": {
        "symbol": "600519.SH",
        "summary": "维持持有，不建议继续加仓，原因不是看空，而是组合集中度过高。",
        "drivers": [
            "白酒龙头趋势仍完整。",
            "持仓市值已占组合过半，需要控制单票暴露。",
        ],
        "risk_notes": ["高价股波动对净值影响更直接。"],
        "sources": ["mock:daily_bar", "mock:portfolio_context"],
    },
}

BUYABLE_SYMBOLS = {item.symbol for item in INSTRUMENTS}
ORDER_SIDES = {OrderSide.BUY.value, OrderSide.SELL.value}

