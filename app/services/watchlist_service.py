import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import watchlist as watchlist_crud
from app.models.watchlist_stock import WatchlistStock
from app.schemas.watchlist import WatchlistCreateRequest

logger = logging.getLogger(__name__)


def _auto_detect_ticker(company_name: str) -> tuple[str | None, str | None]:
    """Try to find the NSE/BSE ticker for the given company name via yfinance search.

    Returns (symbol, exchange) where exchange is 'NSE' or 'BSE', or (None, None)
    if no Indian equity ticker could be found.
    """
    try:
        import yfinance as yf
        search = yf.Search(company_name, max_results=10)
        for quote in search.quotes:
            sym = quote.get("symbol", "")
            if sym.endswith(".NS"):
                return sym[:-3], "NSE"
            elif sym.endswith(".BO"):
                return sym[:-3], "BSE"
    except Exception:
        logger.debug("Ticker auto-detection failed for %r", company_name)
    return None, None


def list_watchlist_for_user(db: Session, *, user_id: uuid.UUID) -> list[WatchlistStock]:
    return watchlist_crud.list_watchlist_by_user(db, user_id=user_id)


def add_watchlist_for_user(
    db: Session,
    *,
    user_id: uuid.UUID,
    payload: WatchlistCreateRequest,
) -> WatchlistStock:
    existing = watchlist_crud.get_watchlist_stock_by_company_name(
        db,
        user_id=user_id,
        company_name=payload.company_name,
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stock already exists in watchlist",
        )

    stock_count = watchlist_crud.count_watchlist_stocks(db, user_id=user_id)
    if stock_count >= settings.WATCHLIST_MAX_STOCKS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Watchlist limit reached ({settings.WATCHLIST_MAX_STOCKS} stocks)",
        )

    symbol, exchange = _auto_detect_ticker(payload.company_name)
    if symbol:
        logger.info("Auto-detected ticker for %r: %s (%s)", payload.company_name, symbol, exchange)
    else:
        logger.info("No ticker found for %r — price data will be unavailable", payload.company_name)

    return watchlist_crud.create_watchlist_stock(
        db,
        user_id=user_id,
        company_name=payload.company_name,
        symbol=symbol,
        exchange=exchange,
    )


def delete_watchlist_for_user(db: Session, *, user_id: uuid.UUID, stock_id: uuid.UUID) -> None:
    stock = watchlist_crud.get_watchlist_stock_by_id(db, stock_id=stock_id, user_id=user_id)
    if stock is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist stock not found")
    watchlist_crud.delete_watchlist_stock(db, stock=stock)
