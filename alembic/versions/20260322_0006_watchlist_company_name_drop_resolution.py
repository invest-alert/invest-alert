"""Replace watchlist resolution columns with company_name; drop resolved_symbol from daily_contexts.

Revision ID: 20260322_0006
Revises: 20260315_0005
Create Date: 2026-03-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260322_0006"
down_revision: Union[str, Sequence[str], None] = "20260315_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- watchlist_stocks -------------------------------------------------
    # Add company_name (nullable so existing rows are safe); we back-fill
    # with the stock symbol so no row is left empty.
    op.add_column(
        "watchlist_stocks",
        sa.Column("company_name", sa.String(length=100), nullable=True),
    )
    op.execute("UPDATE watchlist_stocks SET company_name = symbol WHERE company_name IS NULL")
    op.alter_column("watchlist_stocks", "company_name", nullable=False)

    # Drop the three Marketaux resolution columns.
    op.drop_column("watchlist_stocks", "resolved_symbol")
    op.drop_column("watchlist_stocks", "resolved_company_name")
    op.drop_column("watchlist_stocks", "last_resolved_at")

    # --- daily_contexts ---------------------------------------------------
    # resolved_symbol was always the same as input_symbol once resolution is
    # gone — drop it to keep the table clean.
    op.drop_column("daily_contexts", "resolved_symbol")


def downgrade() -> None:
    # daily_contexts
    op.add_column(
        "daily_contexts",
        sa.Column("resolved_symbol", sa.String(length=32), nullable=True),
    )

    # watchlist_stocks
    op.add_column(
        "watchlist_stocks",
        sa.Column("last_resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "watchlist_stocks",
        sa.Column("resolved_company_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "watchlist_stocks",
        sa.Column("resolved_symbol", sa.String(length=32), nullable=True),
    )
    op.drop_column("watchlist_stocks", "company_name")
