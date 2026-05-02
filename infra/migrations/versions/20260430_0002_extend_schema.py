"""extend schema with all missing tables

Revision ID: 20260430_0002
Revises: 20260425_0001
Create Date: 2026-04-30 09:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260430_0002"
down_revision = "20260425_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("exchange", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("industry", sa.String(128), nullable=False, server_default="unknown"),
        sa.Column("list_date", sa.String(16), nullable=True),
        sa.Column("delist_date", sa.String(16), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="listed"),
        sa.Column("is_st", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "trading_calendar",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_date", sa.String(16), nullable=False, index=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("session_type", sa.String(32), nullable=False, server_default="regular"),
        sa.UniqueConstraint("trade_date", "market", name="uq_calendar_date_market"),
    )

    op.create_table(
        "market_bar_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("trade_date", sa.String(16), nullable=False, index=True),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("turnover_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("adj_type", sa.String(8), nullable=False, server_default="qfq"),
        sa.Column("data_source", sa.String(32), nullable=False),
        sa.UniqueConstraint("symbol", "trade_date", "adj_type", name="uq_bar_symbol_date_adj"),
    )

    op.create_table(
        "news_articles",
        sa.Column("article_id", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(128), nullable=False, index=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("url", sa.String(1024), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "news_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("article_id", sa.String(64), nullable=False, index=True),
        sa.Column("event_type", sa.String(64), nullable=False, index=True),
        sa.Column("sentiment_score", sa.Float(), nullable=False),
        sa.Column("urgency_score", sa.Float(), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("llm_reasoning_version", sa.String(64), nullable=False, server_default="keyword_v1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False, server_default="LIMIT"),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("broker_order_id", sa.String(128), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="MANUAL"),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "trade_fills",
        sa.Column("fill_id", sa.String(64), primary_key=True),
        sa.Column("order_id", sa.String(64), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("fill_price", sa.Float(), nullable=False),
        sa.Column("fill_quantity", sa.Integer(), nullable=False),
        sa.Column("fill_time", sa.DateTime(), nullable=False, index=True),
        sa.Column("commission", sa.Float(), nullable=False, server_default="0"),
    )

    op.create_table(
        "risk_rules",
        sa.Column("rule_id", sa.String(64), primary_key=True),
        sa.Column("rule_type", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("action_on_breach", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "risk_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("rule_id", sa.String(64), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=True, index=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "signal_snapshots",
        sa.Column("signal_id", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("as_of_time", sa.DateTime(), nullable=False, index=True),
        sa.Column("signal_type", sa.String(32), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("expected_horizon", sa.String(64), nullable=False, server_default="swing_5d"),
        sa.Column("model_version", sa.String(64), nullable=False, server_default="v1"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("log_id", sa.String(64), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("signal_snapshots")
    op.drop_table("risk_events")
    op.drop_table("risk_rules")
    op.drop_table("trade_fills")
    op.drop_table("orders")
    op.drop_table("news_events")
    op.drop_table("news_articles")
    op.drop_table("market_bar_daily")
    op.drop_table("trading_calendar")
    op.drop_table("instruments")
