import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy import Uuid as SQLUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ArticleSummaryCache(Base):
    __tablename__ = "article_summary_cache"

    id: Mapped[uuid.UUID] = mapped_column(SQLUuid, primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_source: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
