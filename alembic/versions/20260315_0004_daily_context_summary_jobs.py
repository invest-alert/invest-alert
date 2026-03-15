"""Add daily context summary job tracking.

Revision ID: 20260315_0004
Revises: 20260313_0003
Create Date: 2026-03-15 22:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260315_0004"
down_revision: Union[str, Sequence[str], None] = "20260313_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("daily_contexts", sa.Column("summary_job_id", sa.String(length=64), nullable=True))
    op.add_column(
        "daily_contexts",
        sa.Column("summary_status", sa.String(length=32), nullable=False, server_default="not_available"),
    )
    op.add_column("daily_contexts", sa.Column("summary_error", sa.Text(), nullable=True))
    op.add_column("daily_contexts", sa.Column("summary_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("daily_contexts", sa.Column("summary_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_contexts", "summary_completed_at")
    op.drop_column("daily_contexts", "summary_requested_at")
    op.drop_column("daily_contexts", "summary_error")
    op.drop_column("daily_contexts", "summary_status")
    op.drop_column("daily_contexts", "summary_job_id")
