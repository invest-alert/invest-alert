import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.responses import success_response
from app.models.user import User
from app.schemas.watchlist import WatchlistCreateRequest
from app.services import watchlist_service

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("")
def list_watchlist(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stocks = watchlist_service.list_watchlist_for_user(db, user_id=current_user.id)
    return success_response(data=stocks, message="Watchlist fetched successfully")


@router.post("", status_code=status.HTTP_201_CREATED)
def add_watchlist_stock(
    payload: WatchlistCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stock = watchlist_service.add_watchlist_for_user(db, user_id=current_user.id, payload=payload)
    return success_response(
        data=stock,
        message="Stock added to watchlist successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.delete("/{stock_id}")
def delete_watchlist_stock(
    stock_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    watchlist_service.delete_watchlist_for_user(db, user_id=current_user.id, stock_id=stock_id)
    return success_response(message="Stock removed from watchlist successfully")
