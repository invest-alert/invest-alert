import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy import Uuid as SQLUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DailyContext(Base):
    __tablename__ = "daily_contexts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "watchlist_stock_id",
            "context_date",
            name="uq_daily_context_user_stock_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(SQLUuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        SQLUuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    watchlist_stock_id: Mapped[uuid.UUID] = mapped_column(
        SQLUuid,
        ForeignKey("watchlist_stocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    context_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    price_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_symbol: Mapped[str] = mapped_column(String(120), nullable=False)
    resolved_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    close_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    previous_close: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_change_percent: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    top_headlines: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    summary_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_available")
    summary_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", back_populates="daily_contexts")
    watchlist_stock = relationship("WatchlistStock", back_populates="daily_contexts")
