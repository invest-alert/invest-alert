from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.responses import success_response
from app.models.user import User
from app.services import daily_context_service
from app.services.marketaux_service import MarketauxError

router = APIRouter(prefix="/daily-context", tags=["daily-context"])


@router.get("")
def list_daily_context(
    context_date: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contexts = daily_context_service.list_daily_contexts_for_user(
        db,
        user_id=current_user.id,
        context_date=context_date,
    )
    return success_response(data=contexts, message="Daily context fetched successfully")


@router.post("/harvest", status_code=status.HTTP_201_CREATED)
def harvest_daily_context(
    context_date: date | None = Query(default=None, alias="date"),
    force_refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        summary = daily_context_service.harvest_daily_contexts_for_user(
            db,
            user_id=current_user.id,
            target_date=context_date,
            force_refresh=force_refresh,
        )
    except MarketauxError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return success_response(
        data=summary,
        message="Daily context harvested successfully",
        status_code=status.HTTP_201_CREATED,
    )


