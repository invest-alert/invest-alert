import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.watchlist_stock import WatchlistStock


def list_all_watchlist_stocks(db: Session) -> list[WatchlistStock]:
    stocks = db.scalars(select(WatchlistStock).order_by(WatchlistStock.created_at.asc())).all()
    return list(stocks)


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


def update_watchlist_resolution(
    db: Session,
    *,
    stock: WatchlistStock,
    resolved_symbol: str | None,
    resolved_company_name: str | None,
    last_resolved_at: datetime,
) -> WatchlistStock:
    stock.resolved_symbol = resolved_symbol
    stock.resolved_company_name = resolved_company_name
    stock.last_resolved_at = last_resolved_at
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
