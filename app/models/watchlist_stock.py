import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy import Uuid as SQLUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WatchlistStock(Base):
    __tablename__ = "watchlist_stocks"
    __table_args__ = (
        UniqueConstraint("user_id", "company_name", name="uq_user_company_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(SQLUuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        SQLUuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str | None] = mapped_column(String(120), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(10), nullable=True)
    company_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", back_populates="watchlist_stocks")
    daily_contexts = relationship(
        "DailyContext",
        back_populates="watchlist_stock",
        cascade="all, delete-orphan",
    )
