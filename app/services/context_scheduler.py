import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.db.session import SessionLocal
from app.services import article_summary_service
from app.services import daily_context_service

logger = logging.getLogger(__name__)


def run_scheduled_daily_context_harvest() -> None:
    db = SessionLocal()
    try:
        processed_users = daily_context_service.harvest_daily_contexts_for_all_users(db)
        logger.info("Daily context scheduler processed %s users", processed_users)
    except Exception:
        logger.exception("Daily context scheduler failed")
    finally:
        db.close()


def run_summary_worker_batch() -> None:
    db = SessionLocal()
    try:
        processed_jobs = article_summary_service.process_pending_summary_jobs(
            db,
            limit=settings.SUMMARY_WORKER_BATCH_SIZE,
        )
        if processed_jobs:
            logger.info("Summary worker processed %s job(s)", processed_jobs)
    except Exception:
        logger.exception("Summary worker failed")
    finally:
        db.close()


def start_context_scheduler() -> AsyncIOScheduler | None:
    if not settings.ENABLE_CONTEXT_SCHEDULER and not settings.ENABLE_SUMMARY_WORKER:
        return None

    scheduler = AsyncIOScheduler(timezone=settings.CONTEXT_HARVEST_TIMEZONE)
    if settings.ENABLE_CONTEXT_SCHEDULER:
        scheduler.add_job(
            run_scheduled_daily_context_harvest,
            trigger="cron",
            hour=settings.CONTEXT_HARVEST_HOUR,
            minute=settings.CONTEXT_HARVEST_MINUTE,
            id="daily-context-harvest",
            replace_existing=True,
            max_instances=1,
        )
    if settings.ENABLE_SUMMARY_WORKER:
        scheduler.add_job(
            run_summary_worker_batch,
            trigger="interval",
            seconds=settings.SUMMARY_WORKER_INTERVAL_SECONDS,
            id="summary-worker",
            replace_existing=True,
            max_instances=1,
        )
    scheduler.start()
    if settings.ENABLE_CONTEXT_SCHEDULER:
        logger.info(
            "Daily context scheduler started for %02d:%02d %s",
            settings.CONTEXT_HARVEST_HOUR,
            settings.CONTEXT_HARVEST_MINUTE,
            settings.CONTEXT_HARVEST_TIMEZONE,
        )
    if settings.ENABLE_SUMMARY_WORKER:
        logger.info(
            "Summary worker scheduler started with %ss interval",
            settings.SUMMARY_WORKER_INTERVAL_SECONDS,
        )
    return scheduler


def stop_context_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    if scheduler is None:
        return

    if scheduler.running:
        scheduler.shutdown(wait=False)
