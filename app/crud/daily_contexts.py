from datetime import date, datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.daily_context import DailyContext


def list_daily_contexts_by_user(
    db: Session,
    *,
    user_id: uuid.UUID,
    context_date: date | None = None,
) -> list[DailyContext]:
    stmt = (
        select(DailyContext)
        .where(DailyContext.user_id == user_id)
        .order_by(DailyContext.context_date.desc(), DailyContext.fetched_at.desc())
    )
    if context_date is not None:
        stmt = stmt.where(DailyContext.context_date == context_date)
    contexts = db.scalars(stmt).all()
    return list(contexts)


def get_daily_context_by_user_stock_date(
    db: Session,
    *,
    user_id: uuid.UUID,
    watchlist_stock_id: uuid.UUID,
    context_date: date,
) -> DailyContext | None:
    return db.scalar(
        select(DailyContext).where(
            DailyContext.user_id == user_id,
            DailyContext.watchlist_stock_id == watchlist_stock_id,
            DailyContext.context_date == context_date,
        )
    )


def get_daily_context_by_id(
    db: Session,
    *,
    context_id: uuid.UUID,
) -> DailyContext | None:
    return db.scalar(select(DailyContext).where(DailyContext.id == context_id))


def get_daily_context_by_summary_job_id(
    db: Session,
    *,
    user_id: uuid.UUID,
    summary_job_id: str,
) -> DailyContext | None:
    return db.scalar(
        select(DailyContext).where(
            DailyContext.user_id == user_id,
            DailyContext.summary_job_id == summary_job_id,
        )
    )


def upsert_daily_context(
    db: Session,
    *,
    existing_context: DailyContext | None,
    user_id: uuid.UUID,
    watchlist_stock_id: uuid.UUID,
    context_date: date,
    price_date: date | None,
    company_name: str,
    input_symbol: str,
    resolved_symbol: str | None,
    exchange: str,
    close_price: float | None,
    previous_close: float | None,
    price_change_percent: float | None,
    currency: str | None,
    top_headlines: list[dict],
    article_count: int,
    summary_status: str,
    summary_job_id: str | None,
    summary_error: str | None,
    summary_requested_at: datetime | None,
    summary_completed_at: datetime | None,
    fetched_at: datetime,
) -> DailyContext:
    context = existing_context or DailyContext(
        user_id=user_id,
        watchlist_stock_id=watchlist_stock_id,
        context_date=context_date,
    )
    context.price_date = price_date
    context.company_name = company_name
    context.input_symbol = input_symbol
    context.resolved_symbol = resolved_symbol
    context.exchange = exchange
    context.close_price = close_price
    context.previous_close = previous_close
    context.price_change_percent = price_change_percent
    context.currency = currency
    context.top_headlines = top_headlines
    context.article_count = article_count
    context.summary_status = summary_status
    context.summary_job_id = summary_job_id
    context.summary_error = summary_error
    context.summary_requested_at = summary_requested_at
    context.summary_completed_at = summary_completed_at
    context.fetched_at = fetched_at

    db.add(context)
    db.commit()
    db.refresh(context)
    return context


def update_summary_job(
    db: Session,
    *,
    context: DailyContext,
    summary_status: str,
    summary_job_id: str | None = None,
    summary_error: str | None = None,
    summary_requested_at: datetime | None = None,
    summary_completed_at: datetime | None = None,
    top_headlines: list[dict] | None = None,
) -> DailyContext:
    context.summary_status = summary_status
    context.summary_job_id = summary_job_id
    context.summary_error = summary_error
    context.summary_requested_at = summary_requested_at
    context.summary_completed_at = summary_completed_at
    if top_headlines is not None:
        context.top_headlines = top_headlines

    db.add(context)
    db.commit()
    db.refresh(context)
    return context


def update_headline_summaries(
    db: Session,
    *,
    context: DailyContext,
    top_headlines: list[dict],
    summary_status: str,
    summary_error: str | None,
    summary_completed_at: datetime | None,
) -> DailyContext:
    context.top_headlines = top_headlines
    context.summary_status = summary_status
    context.summary_error = summary_error
    context.summary_completed_at = summary_completed_at

    db.add(context)
    db.commit()
    db.refresh(context)
    return context
