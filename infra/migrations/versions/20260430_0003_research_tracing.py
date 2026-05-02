"""add factor_snapshot, model_run, market_bar_1m tables for research tracing

Revision ID: 20260430_0003
Revises: 20260430_0002
Create Date: 2026-04-30 14:55:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260430_0003"
down_revision = "20260430_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # factor_snapshot — versioned feature values for traceability
    op.create_table(
        "factor_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("as_of_time", sa.DateTime, nullable=False, index=True),
        sa.Column("factor_name", sa.String(64), nullable=False, index=True),
        sa.Column("factor_value", sa.Float, nullable=False),
        sa.Column("feature_set_version", sa.String(32), nullable=False),
        sa.Column("data_source", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint(
            "symbol", "as_of_time", "factor_name", "feature_set_version",
            name="uq_factor_snapshot",
        ),
    )

    # model_run — record every model training / inference run
    op.create_table(
        "model_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("model_name", sa.String(64), nullable=False, index=True),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column("run_type", sa.String(16), nullable=False),  # train | infer | backtest
        sa.Column("train_window_start", sa.Date, nullable=True),
        sa.Column("train_window_end", sa.Date, nullable=True),
        sa.Column("score_metrics", sa.Text, nullable=True),  # JSON
        sa.Column("params", sa.Text, nullable=True),         # JSON
        sa.Column("artifact_uri", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
    )

    # market_bar_1m — minute K-line (placeholder schema; ingest is opt-in)
    op.create_table(
        "market_bar_1m",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("bar_time", sa.DateTime, nullable=False, index=True),
        sa.Column("open", sa.Float, nullable=False),
        sa.Column("high", sa.Float, nullable=False),
        sa.Column("low", sa.Float, nullable=False),
        sa.Column("close", sa.Float, nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False),
        sa.Column("amount", sa.Float, nullable=True),
        sa.Column("data_source", sa.String(32), nullable=False),
        sa.UniqueConstraint("symbol", "bar_time", "data_source",
                            name="uq_bar1m_symbol_time"),
    )


def downgrade() -> None:
    op.drop_table("market_bar_1m")
    op.drop_table("model_runs")
    op.drop_table("factor_snapshots")
