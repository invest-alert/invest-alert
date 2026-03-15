"""Add Postgres-backed summary queue and cache.

Revision ID: 20260315_0005
Revises: 20260315_0004
Create Date: 2026-03-15 23:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260315_0005"
down_revision: Union[str, Sequence[str], None] = "20260315_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "article_summary_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content_excerpt", sa.Text(), nullable=True),
        sa.Column("summary_source", sa.String(length=32), nullable=False),
        sa.Column("summary_generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_hash"),
    )
    op.create_index(
        op.f("ix_article_summary_cache_url_hash"),
        "article_summary_cache",
        ["url_hash"],
        unique=True,
    )

    op.create_table(
        "summary_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("daily_context_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["daily_context_id"], ["daily_contexts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("daily_context_id", name="uq_summary_jobs_daily_context_id"),
    )
    op.create_index(op.f("ix_summary_jobs_daily_context_id"), "summary_jobs", ["daily_context_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_summary_jobs_daily_context_id"), table_name="summary_jobs")
    op.drop_table("summary_jobs")

    op.drop_index(op.f("ix_article_summary_cache_url_hash"), table_name="article_summary_cache")
    op.drop_table("article_summary_cache")
