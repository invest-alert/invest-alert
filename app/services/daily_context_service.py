import logging
import re
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import daily_contexts as daily_context_crud
from app.crud import users as user_crud
from app.crud import watchlist as watchlist_crud
from app.models.daily_context import DailyContext
from app.models.watchlist_stock import WatchlistStock
from app.schemas.daily_context import DailyContextHarvestSummary
from app.services.article_summary_service import (
    SUMMARY_STATUS_NOT_AVAILABLE,
    SUMMARY_STATUS_QUEUED,
    enqueue_daily_context_summary_job,
    initialize_headline_summary_fields,
)
from app.services.google_news_service import GoogleNewsError, fetch_company_news as fetch_google_news
from app.services.market_price_service import MarketPriceError, PriceSnapshot, fetch_price_snapshot
from app.services.marketaux_service import MarketauxError, fetch_company_news, resolve_equity

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fallback_symbol(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def list_daily_contexts_for_user(
    db: Session,
    *,
    user_id,
    context_date: date | None = None,
) -> list[DailyContext]:
    return daily_context_crud.list_daily_contexts_by_user(db, user_id=user_id, context_date=context_date)


def _resolve_watchlist_stock(db: Session, stock: WatchlistStock) -> tuple[str, str]:
    if stock.resolved_symbol and stock.resolved_company_name:
        return stock.resolved_symbol, stock.resolved_company_name

    resolved_entity = resolve_equity(stock.symbol, stock.exchange)
    if resolved_entity is not None:
        updated_stock = watchlist_crud.update_watchlist_resolution(
            db,
            stock=stock,
            resolved_symbol=resolved_entity.symbol,
            resolved_company_name=resolved_entity.company_name,
            last_resolved_at=_utc_now(),
        )
        return updated_stock.resolved_symbol or resolved_entity.symbol, (
            updated_stock.resolved_company_name or resolved_entity.company_name
        )

    fallback_symbol = _fallback_symbol(stock.symbol)
    if not fallback_symbol:
        raise MarketauxError(f"Unable to resolve a market symbol for watchlist stock '{stock.symbol}'")
    return fallback_symbol, stock.symbol


def _create_context_record(
    db: Session,
    *,
    stock: WatchlistStock,
    target_date: date,
    resolved_symbol: str,
    company_name: str,
    price_snapshot: PriceSnapshot | None,
    top_headlines: list[dict],
) -> DailyContext:
    initialized_headlines = initialize_headline_summary_fields(top_headlines)
    has_headlines = len(initialized_headlines) > 0
    existing_context = daily_context_crud.get_daily_context_by_user_stock_date(
        db,
        user_id=stock.user_id,
        watchlist_stock_id=stock.id,
        context_date=target_date,
    )
    return daily_context_crud.upsert_daily_context(
        db,
        existing_context=existing_context,
        user_id=stock.user_id,
        watchlist_stock_id=stock.id,
        context_date=target_date,
        price_date=price_snapshot.price_date if price_snapshot else None,
        company_name=company_name,
        input_symbol=stock.symbol,
        resolved_symbol=resolved_symbol,
        exchange=stock.exchange,
        close_price=price_snapshot.close_price if price_snapshot else None,
        previous_close=price_snapshot.previous_close if price_snapshot else None,
        price_change_percent=price_snapshot.price_change_percent if price_snapshot else None,
        currency=price_snapshot.currency if price_snapshot else None,
        top_headlines=initialized_headlines,
        article_count=len(initialized_headlines),
        summary_status=SUMMARY_STATUS_QUEUED if has_headlines else SUMMARY_STATUS_NOT_AVAILABLE,
        summary_job_id=None,
        summary_error=None,
        summary_requested_at=None,
        summary_completed_at=None if has_headlines else _utc_now(),
        fetched_at=_utc_now(),
    )


def harvest_daily_contexts_for_user(
    db: Session,
    *,
    user_id,
    target_date: date | None = None,
) -> DailyContextHarvestSummary:
    harvest_date = target_date or date.today()
    watchlist_stocks = watchlist_crud.list_watchlist_by_user(db, user_id=user_id)
    saved_contexts: list[DailyContext] = []

    for stock in watchlist_stocks:
        resolved_symbol, company_name = _resolve_watchlist_stock(db, stock)

        try:
            price_snapshot = fetch_price_snapshot(
                resolved_symbol,
                stock.exchange,
                search_query=company_name,
            )
        except MarketPriceError as exc:
            logger.warning("Price fetch failed for %s (%s): %s", stock.symbol, stock.exchange, exc)
            price_snapshot = None

        top_headlines: list[dict] = []
        try:
            top_headlines = fetch_company_news(
                company_name,
                market_symbol=resolved_symbol,
                target_date=harvest_date,
                article_limit=settings.DAILY_CONTEXT_ARTICLE_LIMIT,
            )
        except MarketauxError as exc:
            logger.warning("Marketaux news fetch failed for %s: %s", company_name, exc)

        if not top_headlines:
            try:
                top_headlines = fetch_google_news(
                    company_name,
                    target_date=harvest_date,
                    article_limit=settings.DAILY_CONTEXT_ARTICLE_LIMIT,
                )
            except GoogleNewsError as exc:
                logger.warning("Google News fallback failed for %s: %s", company_name, exc)

        saved_context = _create_context_record(
            db,
            stock=stock,
            target_date=harvest_date,
            resolved_symbol=resolved_symbol,
            company_name=company_name,
            price_snapshot=price_snapshot,
            top_headlines=top_headlines,
        )
        saved_context = enqueue_daily_context_summary_job(db, context=saved_context)
        saved_contexts.append(saved_context)

    return DailyContextHarvestSummary(
        target_date=harvest_date,
        processed_count=len(watchlist_stocks),
        saved_count=len(saved_contexts),
        contexts=saved_contexts,
    )


def harvest_daily_contexts_for_all_users(db: Session, *, target_date: date | None = None) -> int:
    processed_users = 0
    for user in user_crud.list_users(db):
        try:
            harvest_daily_contexts_for_user(db, user_id=user.id, target_date=target_date)
            processed_users += 1
        except MarketauxError:
            logger.exception("Daily context harvest failed for user %s", user.id)
            raise
        except Exception:
            logger.exception("Unexpected daily context harvest failure for user %s", user.id)
    return processed_users
