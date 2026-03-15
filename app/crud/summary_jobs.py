from datetime import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.summary_job import SummaryJob


def get_summary_job_by_id(db: Session, *, job_id: uuid.UUID) -> SummaryJob | None:
    return db.scalar(select(SummaryJob).where(SummaryJob.id == job_id))


def get_summary_job_by_daily_context_id(db: Session, *, daily_context_id: uuid.UUID) -> SummaryJob | None:
    return db.scalar(
        select(SummaryJob).where(SummaryJob.daily_context_id == daily_context_id)
    )


def list_summary_jobs_by_status(
    db: Session,
    *,
    statuses: list[str],
    limit: int,
) -> list[SummaryJob]:
    stmt = (
        select(SummaryJob)
        .where(SummaryJob.status.in_(statuses))
        .order_by(SummaryJob.queued_at.asc(), SummaryJob.created_at.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def upsert_summary_job(
    db: Session,
    *,
    daily_context_id: uuid.UUID,
    status: str,
    queued_at: datetime,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    last_error: str | None = None,
    retry_count: int = 0,
) -> SummaryJob:
    job = get_summary_job_by_daily_context_id(db, daily_context_id=daily_context_id)
    if job is None:
        job = SummaryJob(daily_context_id=daily_context_id)
        db.add(job)

    job.status = status
    job.queued_at = queued_at
    job.started_at = started_at
    job.completed_at = completed_at
    job.last_error = last_error
    job.retry_count = retry_count

    db.commit()
    db.refresh(job)
    return job


def update_summary_job(
    db: Session,
    *,
    job: SummaryJob,
    status: str,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    last_error: str | None = None,
    retry_count: int | None = None,
) -> SummaryJob:
    job.status = status
    job.started_at = started_at
    job.completed_at = completed_at
    job.last_error = last_error
    if retry_count is not None:
        job.retry_count = retry_count

    db.add(job)
    db.commit()
    db.refresh(job)
    return job
