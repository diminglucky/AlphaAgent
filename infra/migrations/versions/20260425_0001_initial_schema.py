"""initial schema

Revision ID: 20260425_0001
Revises: 
Create Date: 2026-04-25 18:30:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260425_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshots",
        sa.Column("account_id", sa.String(length=64), primary_key=True),
        sa.Column("portfolio_name", sa.String(length=255), nullable=False),
        sa.Column("base_currency", sa.String(length=16), nullable=False),
        sa.Column("total_asset", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("market_value", sa.Float(), nullable=False),
        sa.Column("daily_pnl", sa.Float(), nullable=False),
        sa.Column("total_pnl", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "positions",
        sa.Column("position_id", sa.String(length=64), primary_key=True),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("available_quantity", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.Float(), nullable=False),
        sa.Column("market_value", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_positions_account_id", "positions", ["account_id"], unique=False)
    op.create_index("ix_positions_symbol", "positions", ["symbol"], unique=False)

    op.create_table(
        "recommendations",
        sa.Column("recommendation_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("target_weight", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("time_horizon", sa.String(length=64), nullable=False),
        sa.Column("reason_summary", sa.Text(), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_recommendations_created_at", "recommendations", ["created_at"], unique=False)
    op.create_index("ix_recommendations_symbol", "recommendations", ["symbol"], unique=False)

    op.create_table(
        "recommendation_explanations",
        sa.Column("symbol", sa.String(length=32), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("drivers", sa.JSON(), nullable=False),
        sa.Column("risk_notes", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recommendation_explanations")
    op.drop_index("ix_recommendations_symbol", table_name="recommendations")
    op.drop_index("ix_recommendations_created_at", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_positions_symbol", table_name="positions")
    op.drop_index("ix_positions_account_id", table_name="positions")
    op.drop_table("positions")
    op.drop_table("portfolio_snapshots")

