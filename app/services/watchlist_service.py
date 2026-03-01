import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import watchlist as watchlist_crud
from app.models.watchlist_stock import WatchlistStock
from app.schemas.watchlist import WatchlistCreateRequest


def list_watchlist_for_user(db: Session, *, user_id: uuid.UUID) -> list[WatchlistStock]:
    return watchlist_crud.list_watchlist_by_user(db, user_id=user_id)


def add_watchlist_for_user(
    db: Session,
    *,
    user_id: uuid.UUID,
    payload: WatchlistCreateRequest,
) -> WatchlistStock:
    existing = watchlist_crud.get_watchlist_stock_by_symbol(
        db,
        user_id=user_id,
        symbol=payload.symbol,
        exchange=payload.exchange,
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

    return watchlist_crud.create_watchlist_stock(
        db,
        user_id=user_id,
        symbol=payload.symbol,
        exchange=payload.exchange,
    )


def delete_watchlist_for_user(db: Session, *, user_id: uuid.UUID, stock_id: uuid.UUID) -> None:
    stock = watchlist_crud.get_watchlist_stock_by_id(db, stock_id=stock_id, user_id=user_id)
    if stock is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist stock not found")
    watchlist_crud.delete_watchlist_stock(db, stock=stock)
