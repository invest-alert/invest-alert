from datetime import date
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.responses import success_response
from app.crud import daily_contexts as daily_context_crud
from app.models.user import User
from app.services import article_summary_service
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        summary = daily_context_service.harvest_daily_contexts_for_user(
            db,
            user_id=current_user.id,
            target_date=context_date,
        )
    except MarketauxError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return success_response(
        data=summary,
        message="Daily context harvested successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/{context_id}/summaries", status_code=status.HTTP_202_ACCEPTED)
def enqueue_daily_context_summaries(
    context_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    context = daily_context_crud.get_daily_context_by_id(db, context_id=context_id)
    if context is None or context.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily context not found")

    updated_context = article_summary_service.enqueue_daily_context_summary_job(db, context=context)
    return success_response(
        data=updated_context,
        message="Daily context summary job queued successfully",
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.get("/tasks/{task_id}")
def get_summary_task_status(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        status_payload = article_summary_service.get_summary_task_status(
            db,
            user_id=current_user.id,
            task_id=task_id,
        )
    except article_summary_service.ArticleSummaryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return success_response(data=status_payload, message="Summary task status fetched successfully")
