"""Make watchlist symbol/exchange optional; make daily_context input_symbol/exchange nullable.

Revision ID: 20260322_0007
Revises: 20260322_0006
Create Date: 2026-03-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260322_0007"
down_revision: Union[str, Sequence[str], None] = "20260322_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- watchlist_stocks ---
    # Drop old constraints that required symbol/exchange
    op.drop_constraint("uq_user_symbol_exchange", "watchlist_stocks", type_="unique")
    op.drop_constraint("ck_watchlist_exchange", "watchlist_stocks", type_="check")

    # Make symbol and exchange optional (auto-detected via yfinance)
    op.alter_column("watchlist_stocks", "symbol", nullable=True)
    op.alter_column("watchlist_stocks", "exchange", nullable=True)

    # New unique constraint: one entry per company name per user
    op.create_unique_constraint(
        "uq_user_company_name", "watchlist_stocks", ["user_id", "company_name"]
    )

    # --- daily_contexts ---
    # input_symbol and exchange can now be NULL when no ticker was auto-detected
    op.alter_column("daily_contexts", "input_symbol", nullable=True)
    op.alter_column("daily_contexts", "exchange", nullable=True)


def downgrade() -> None:
    op.alter_column("daily_contexts", "exchange", nullable=False)
    op.alter_column("daily_contexts", "input_symbol", nullable=False)

    op.drop_constraint("uq_user_company_name", "watchlist_stocks", type_="unique")
    op.alter_column("watchlist_stocks", "exchange", nullable=False)
    op.alter_column("watchlist_stocks", "symbol", nullable=False)
    op.create_check_constraint(
        "ck_watchlist_exchange", "watchlist_stocks", "exchange IN ('NSE', 'BSE')"
    )
    op.create_unique_constraint(
        "uq_user_symbol_exchange", "watchlist_stocks", ["user_id", "symbol", "exchange"]
    )
