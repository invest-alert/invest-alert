import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import Uuid as SQLUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SummaryJob(Base):
    __tablename__ = "summary_jobs"
    __table_args__ = (
        UniqueConstraint("daily_context_id", name="uq_summary_jobs_daily_context_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(SQLUuid, primary_key=True, default=uuid.uuid4)
    daily_context_id: Mapped[uuid.UUID] = mapped_column(
        SQLUuid,
        ForeignKey("daily_contexts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    daily_context = relationship("DailyContext")
