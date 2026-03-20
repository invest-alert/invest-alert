import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

import app.db.session as db_session_module
from app.core.config import settings
from app.crud import daily_contexts as daily_context_crud
from app.crud import users as user_crud
from app.crud import watchlist as watchlist_crud
from app.models.daily_context import DailyContext
from app.models.watchlist_stock import WatchlistStock
from app.schemas.daily_context import DailyContextHarvestSummary
from app.services.article_summary_service import SUMMARY_STATUS_NOT_AVAILABLE
from app.services.google_news_service import GoogleNewsError, fetch_company_news
from app.services.market_price_service import (
    MarketPriceError,
    PriceSnapshot,
    fetch_price_snapshot,
    fetch_yfinance_news,
)
from app.services.marketaux_service import MarketauxError, resolve_equity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plain-data containers (thread-safe — no ORM / session references)
# ---------------------------------------------------------------------------


@dataclass
class _FetchJob:
    """Everything a worker thread needs to fetch external data for one stock."""

    stock_id: uuid.UUID
    user_id: uuid.UUID
    symbol: str
    exchange: str
    resolved_symbol: str
    company_name: str


@dataclass
class _FetchResult:
    stock_id: uuid.UUID
    resolved_symbol: str
    company_name: str
    price_snapshot: PriceSnapshot | None
    top_headlines: list[dict]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fallback_symbol(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def _is_context_fresh(context: DailyContext | None, ttl_hours: int) -> bool:
    """Return True when *context* was fetched within the TTL window."""
    if context is None or context.fetched_at is None:
        return False
    fetched_at = context.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return _utc_now() - fetched_at < timedelta(hours=ttl_hours)


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


def _fetch_news_for_company(
    company_name: str,
    resolved_symbol: str,
    harvest_date: date,
) -> list[dict]:
    """Fetch news: Yahoo Finance first, Google News to fill any remaining gaps."""
    limit = settings.DAILY_CONTEXT_ARTICLE_LIMIT
    articles: list[dict] = []

    # Pass 1: Yahoo Finance — fast and already authenticated via yfinance
    try:
        articles = fetch_yfinance_news(resolved_symbol, limit=limit, target_date=harvest_date)
    except Exception:
        pass

    # Pass 2: Google News (businessline-first pass handled inside) to fill gaps
    if len(articles) < limit:
        try:
            google_articles = fetch_company_news(
                company_name,
                target_date=harvest_date,
                article_limit=limit - len(articles) + 3,  # fetch extras to survive dedup
            )
            seen_titles = {a["title"].lower() for a in articles}
            for article in google_articles:
                if len(articles) >= limit:
                    break
                title_lower = article["title"].lower()
                if title_lower not in seen_titles:
                    articles.append(article)
                    seen_titles.add(title_lower)
        except GoogleNewsError as exc:
            logger.warning("Google News fetch failed for %s: %s", company_name, exc)

    return articles[:limit]


def _execute_fetch_job(job: _FetchJob, harvest_date: date) -> _FetchResult:
    """Pure I/O worker — no DB operations, fully thread-safe."""
    logger.info("[%s] Fetching price data (exchange=%s, resolved=%s)…", job.symbol, job.exchange, job.resolved_symbol)
    try:
        price_snapshot = fetch_price_snapshot(
            job.resolved_symbol,
            job.exchange,
            search_query=job.company_name,
        )
        if price_snapshot:
            logger.info(
                "[%s] Price OK — close=%.2f %s, change=%.2f%%",
                job.symbol,
                price_snapshot.close_price or 0,
                price_snapshot.currency or "?",
                price_snapshot.price_change_percent or 0,
            )
        else:
            logger.info("[%s] Price returned None (no snapshot available)", job.symbol)
    except MarketPriceError as exc:
        logger.warning("[%s] Price fetch failed: %s", job.symbol, exc)
        price_snapshot = None

    logger.info("[%s] Fetching news for '%s'…", job.symbol, job.company_name)
    top_headlines = _fetch_news_for_company(job.company_name, job.resolved_symbol, harvest_date)
    logger.info("[%s] News OK — %d article(s) collected", job.symbol, len(top_headlines))

    return _FetchResult(
        stock_id=job.stock_id,
        resolved_symbol=job.resolved_symbol,
        company_name=job.company_name,
        price_snapshot=price_snapshot,
        top_headlines=top_headlines,
    )


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
        top_headlines=top_headlines,
        article_count=len(top_headlines),
        summary_status=SUMMARY_STATUS_NOT_AVAILABLE,
        summary_job_id=None,
        summary_error=None,
        summary_requested_at=None,
        summary_completed_at=_utc_now(),
        fetched_at=_utc_now(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_daily_contexts_for_user(
    db: Session,
    *,
    user_id,
    context_date: date | None = None,
) -> list[DailyContext]:
    return daily_context_crud.list_daily_contexts_by_user(db, user_id=user_id, context_date=context_date)


def harvest_daily_contexts_for_user(
    db: Session,
    *,
    user_id,
    target_date: date | None = None,
    force_refresh: bool = False,
) -> DailyContextHarvestSummary:
    """Harvest daily context for every stock in the user's watchlist.

    Architecture — three phases:
      Phase 1 (sequential, single session): resolve symbols + TTL cache check.
      Phase 2 (parallel I/O, no DB):        fetch price + news for stale stocks.
      Phase 3 (sequential, single session): write fetch results back to DB.

    Splitting I/O into a thread pool while keeping all DB work on the request
    session avoids multi-session concurrency issues with SQLite (tests) and
    eliminates redundant round-trips for fresh records.
    """
    harvest_date = target_date or date.today()
    watchlist_stocks = watchlist_crud.list_watchlist_by_user(db, user_id=user_id)

    logger.info(
        "Harvest started — user=%s, date=%s, stocks=%d, force_refresh=%s",
        user_id, harvest_date, len(watchlist_stocks), force_refresh,
    )

    saved_contexts: list[DailyContext] = []
    fetch_jobs: list[_FetchJob] = []
    stock_map: dict[uuid.UUID, WatchlistStock] = {}
    cache_hit_count = 0

    # ------------------------------------------------------------------
    # Phase 1: sequential — symbol resolution + TTL cache check
    # ------------------------------------------------------------------
    logger.info("Phase 1: resolving symbols and checking TTL cache…")
    for stock in watchlist_stocks:
        resolved_symbol, company_name = _resolve_watchlist_stock(db, stock)
        logger.info(
            "[%s] Resolved → symbol=%s, company='%s'",
            stock.symbol, resolved_symbol, company_name,
        )

        if not force_refresh:
            existing = daily_context_crud.get_daily_context_by_user_stock_date(
                db,
                user_id=stock.user_id,
                watchlist_stock_id=stock.id,
                context_date=harvest_date,
            )
            if _is_context_fresh(existing, settings.DAILY_CONTEXT_CACHE_TTL_HOURS):
                age_hours = (_utc_now() - (
                    existing.fetched_at.replace(tzinfo=timezone.utc)
                    if existing.fetched_at.tzinfo is None else existing.fetched_at
                )).total_seconds() / 3600
                logger.info(
                    "[%s] Cache HIT — data is %.1fh old (TTL=%dh), skipping fetch",
                    stock.symbol, age_hours, settings.DAILY_CONTEXT_CACHE_TTL_HOURS,
                )
                saved_contexts.append(existing)
                cache_hit_count += 1
                continue
            else:
                logger.info("[%s] Cache MISS — queuing for fresh fetch", stock.symbol)

        job = _FetchJob(
            stock_id=stock.id,
            user_id=stock.user_id,
            symbol=stock.symbol,
            exchange=stock.exchange,
            resolved_symbol=resolved_symbol,
            company_name=company_name,
        )
        fetch_jobs.append(job)
        stock_map[stock.id] = stock

    logger.info(
        "Phase 1 complete — %d cache hit(s), %d stock(s) queued for fetch",
        cache_hit_count, len(fetch_jobs),
    )

    # ------------------------------------------------------------------
    # Phase 2: parallel I/O — price + news fetches (no DB operations)
    # ------------------------------------------------------------------
    if fetch_jobs:
        max_workers = min(len(fetch_jobs), settings.HARVEST_MAX_WORKERS)
        logger.info(
            "Phase 2: launching parallel fetch — %d stock(s), max_workers=%d",
            len(fetch_jobs), max_workers,
        )
        fetch_results: list[_FetchResult] = []

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_execute_fetch_job, job, harvest_date): job for job in fetch_jobs}
            for future in as_completed(futures):
                job = futures[future]
                try:
                    fetch_results.append(future.result())
                except Exception:
                    logger.exception("External fetch failed for %s (%s)", job.symbol, job.exchange)

        logger.info("Phase 2 complete — %d result(s) collected", len(fetch_results))

        # --------------------------------------------------------------
        # Phase 3: sequential — write results back to DB (same session)
        # --------------------------------------------------------------
        logger.info("Phase 3: saving %d result(s) to database…", len(fetch_results))
        for result in fetch_results:
            stock = stock_map[result.stock_id]
            saved_context = _create_context_record(
                db,
                stock=stock,
                target_date=harvest_date,
                resolved_symbol=result.resolved_symbol,
                company_name=result.company_name,
                price_snapshot=result.price_snapshot,
                top_headlines=result.top_headlines,
            )
            logger.info("[%s] Saved to DB (id=%s)", stock.symbol, saved_context.id)
            saved_contexts.append(saved_context)

        logger.info("Phase 3 complete — %d record(s) upserted", len(fetch_results))

    logger.info(
        "Harvest done — processed=%d, saved=%d, cache_hits=%d, freshly_fetched=%d",
        len(watchlist_stocks), len(saved_contexts), cache_hit_count, len(fetch_jobs),
    )

    return DailyContextHarvestSummary(
        target_date=harvest_date,
        processed_count=len(watchlist_stocks),
        saved_count=len(saved_contexts),
        cache_hit_count=cache_hit_count,
        contexts=saved_contexts,
    )


def harvest_daily_context_for_single_stock(
    stock_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    target_date: date | None = None,
    force_refresh: bool = True,
) -> None:
    """Background-safe single-stock harvest — creates its own DB session.

    Designed to be called via FastAPI BackgroundTasks after a stock is added
    to the watchlist, so the user gets context without waiting for a full
    harvest.  Always force-refreshes by default (the record won't exist yet).
    """
    db = db_session_module.SessionLocal()
    try:
        stock = watchlist_crud.get_watchlist_stock_by_id(db, stock_id=stock_id, user_id=user_id)
        if stock is None:
            logger.warning("harvest_daily_context_for_single_stock: stock %s not found", stock_id)
            return

        harvest_date = target_date or date.today()
        resolved_symbol, company_name = _resolve_watchlist_stock(db, stock)

        job = _FetchJob(
            stock_id=stock.id,
            user_id=stock.user_id,
            symbol=stock.symbol,
            exchange=stock.exchange,
            resolved_symbol=resolved_symbol,
            company_name=company_name,
        )
        result = _execute_fetch_job(job, harvest_date)

        _create_context_record(
            db,
            stock=stock,
            target_date=harvest_date,
            resolved_symbol=result.resolved_symbol,
            company_name=result.company_name,
            price_snapshot=result.price_snapshot,
            top_headlines=result.top_headlines,
        )
    except Exception:
        logger.exception("Background harvest failed for stock %s", stock_id)
    finally:
        db.close()


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
