import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.responses import success_response
from app.models.user import User
from app.schemas.watchlist import WatchlistCreateRequest
from app.services import watchlist_service
from app.services.daily_context_service import harvest_daily_context_for_single_stock

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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stock = watchlist_service.add_watchlist_for_user(db, user_id=current_user.id, payload=payload)

    # Kick off a context harvest for the new stock in the background so the
    # user gets data shortly after adding — without blocking the response.
    if settings.ENABLE_AUTO_HARVEST_ON_ADD:
        background_tasks.add_task(
            harvest_daily_context_for_single_stock,
            stock.id,
            current_user.id,
        )

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
