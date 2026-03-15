"""Add daily contexts and watchlist resolution metadata.

Revision ID: 20260313_0003
Revises: 20260301_0002
Create Date: 2026-03-13 20:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260313_0003"
down_revision: Union[str, Sequence[str], None] = "20260301_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("watchlist_stocks", sa.Column("resolved_symbol", sa.String(length=32), nullable=True))
    op.add_column(
        "watchlist_stocks",
        sa.Column("resolved_company_name", sa.String(length=255), nullable=True),
    )
    op.add_column("watchlist_stocks", sa.Column("last_resolved_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "daily_contexts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("watchlist_stock_id", sa.Uuid(), nullable=False),
        sa.Column("context_date", sa.Date(), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=True),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("input_symbol", sa.String(length=120), nullable=False),
        sa.Column("resolved_symbol", sa.String(length=32), nullable=True),
        sa.Column("exchange", sa.String(length=10), nullable=False),
        sa.Column("close_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("previous_close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("price_change_percent", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("top_headlines", sa.JSON(), nullable=True),
        sa.Column("article_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watchlist_stock_id"], ["watchlist_stocks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "watchlist_stock_id",
            "context_date",
            name="uq_daily_context_user_stock_date",
        ),
    )
    op.create_index(op.f("ix_daily_contexts_user_id"), "daily_contexts", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_daily_contexts_watchlist_stock_id"),
        "daily_contexts",
        ["watchlist_stock_id"],
        unique=False,
    )
    op.create_index(op.f("ix_daily_contexts_context_date"), "daily_contexts", ["context_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_daily_contexts_context_date"), table_name="daily_contexts")
    op.drop_index(op.f("ix_daily_contexts_watchlist_stock_id"), table_name="daily_contexts")
    op.drop_index(op.f("ix_daily_contexts_user_id"), table_name="daily_contexts")
    op.drop_table("daily_contexts")

    op.drop_column("watchlist_stocks", "last_resolved_at")
    op.drop_column("watchlist_stocks", "resolved_company_name")
    op.drop_column("watchlist_stocks", "resolved_symbol")
