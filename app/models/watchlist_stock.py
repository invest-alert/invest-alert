import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy import Uuid as SQLUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WatchlistStock(Base):
    __tablename__ = "watchlist_stocks"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", "exchange", name="uq_user_symbol_exchange"),
        CheckConstraint("exchange IN ('NSE', 'BSE')", name="ck_watchlist_exchange"),
    )

    id: Mapped[uuid.UUID] = mapped_column(SQLUuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        SQLUuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(120), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    resolved_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", back_populates="watchlist_stocks")
    daily_contexts = relationship(
        "DailyContext",
        back_populates="watchlist_stock",
        cascade="all, delete-orphan",
    )
