import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.watchlist_stock import WatchlistStock


def list_watchlist_by_user(db: Session, *, user_id: uuid.UUID) -> list[WatchlistStock]:
    stocks = db.scalars(
        select(WatchlistStock)
        .where(WatchlistStock.user_id == user_id)
        .order_by(WatchlistStock.created_at.desc())
    ).all()
    return list(stocks)


def get_watchlist_stock_by_symbol(
    db: Session,
    *,
    user_id: uuid.UUID,
    symbol: str,
    exchange: str,
) -> WatchlistStock | None:
    return db.scalar(
        select(WatchlistStock).where(
            WatchlistStock.user_id == user_id,
            WatchlistStock.symbol == symbol,
            WatchlistStock.exchange == exchange,
        )
    )


def count_watchlist_stocks(db: Session, *, user_id: uuid.UUID) -> int:
    count = db.scalar(
        select(func.count()).select_from(WatchlistStock).where(WatchlistStock.user_id == user_id)
    )
    return int(count or 0)


def create_watchlist_stock(
    db: Session,
    *,
    user_id: uuid.UUID,
    symbol: str,
    exchange: str,
) -> WatchlistStock:
    stock = WatchlistStock(user_id=user_id, symbol=symbol, exchange=exchange)
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


def get_watchlist_stock_by_id(
    db: Session,
    *,
    stock_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WatchlistStock | None:
    return db.scalar(
        select(WatchlistStock).where(
            WatchlistStock.id == stock_id,
            WatchlistStock.user_id == user_id,
        )
    )


def delete_watchlist_stock(db: Session, *, stock: WatchlistStock) -> None:
    db.delete(stock)
    db.commit()
