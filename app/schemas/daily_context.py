from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DailyContextHeadline(BaseModel):
    title: str
    url: str | None = None
    source: str | None = None
    published_at: str | None = None
    snippet: str | None = None
    summary: str | None = None
    summary_status: str | None = None
    summary_error: str | None = None
    summary_source: str | None = None
    summary_generated_at: str | None = None
    content_excerpt: str | None = None


class DailyContextItemResponse(BaseModel):
    id: UUID
    context_date: date
    price_date: date | None = None
    company_name: str
    input_symbol: str | None = None
    exchange: str | None = None
    close_price: float | None = None
    previous_close: float | None = None
    price_change_percent: float | None = None
    currency: str | None = None
    top_headlines: list[DailyContextHeadline] | None = None
    article_count: int
    summary_job_id: str | None = None
    summary_status: str
    summary_error: str | None = None
    summary_requested_at: datetime | None = None
    summary_completed_at: datetime | None = None
    fetched_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DailyContextHarvestSummary(BaseModel):
    target_date: date
    processed_count: int
    saved_count: int
    cache_hit_count: int = 0
    contexts: list[DailyContextItemResponse]


class SummaryTaskStatusResponse(BaseModel):
    task_id: str
    status: str
    ready: bool
    successful: bool
    failed: bool
    result: dict | None = None
    error: str | None = None
