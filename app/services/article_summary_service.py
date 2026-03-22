import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import trafilatura
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import article_summary_cache as article_summary_cache_crud
from app.crud import daily_contexts as daily_context_crud
from app.crud import summary_jobs as summary_job_crud
from app.models.daily_context import DailyContext
from app.models.summary_job import SummaryJob

logger = logging.getLogger(__name__)

SUMMARY_STATUS_NOT_AVAILABLE = "not_available"
SUMMARY_STATUS_QUEUED = "queued"
SUMMARY_STATUS_PROCESSING = "processing"
SUMMARY_STATUS_COMPLETED = "completed"
SUMMARY_STATUS_PARTIAL = "partial"
SUMMARY_STATUS_FAILED = "failed"
SUMMARY_STATUS_QUEUE_FAILED = "queue_failed"

HEADLINE_STATUS_PENDING = "pending"
HEADLINE_STATUS_COMPLETED = "completed"
HEADLINE_STATUS_FAILED = "failed"

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "this", "to", "was", "were", "will", "with",
}

_SUMMARY_HEADLINE_FIELDS = {
    "summary",
    "summary_status",
    "summary_error",
    "summary_source",
    "summary_generated_at",
    "content_excerpt",
}

# Bumped from v2 — trafilatura extraction invalidates old BeautifulSoup-based cache entries
_SUMMARY_CACHE_VERSION = "v3"


@dataclass
class ExtractedArticleContent:
    article_text: str
    summary_input: str
    content_excerpt: str
    summary_source: str
    description: str | None = None


class ArticleSummaryError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", _normalize_whitespace(text))
    return [s.strip() for s in sentences if len(s.strip().split()) >= 6]


def _sentence_words(sentence: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{1,}", sentence.lower())
        if token not in _STOP_WORDS
    ]


def _similarity_ratio(sentence: str, reference: str) -> float:
    sentence_words = set(_sentence_words(sentence))
    reference_words = set(_sentence_words(reference))
    if not sentence_words or not reference_words:
        return 0.0
    return len(sentence_words & reference_words) / len(sentence_words)


def _fetch_article_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    logger.debug("Fetching article HTML from: %s", url)
    with httpx.Client(
        follow_redirects=True,
        timeout=settings.SUMMARY_FETCH_TIMEOUT_SECONDS,
        headers=headers,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and "xml" not in content_type:
            raise ArticleSummaryError("Source URL did not return HTML content")
        return response.text


def _extract_article_content(html: str, *, url: str, headline_title: str | None = None) -> ExtractedArticleContent:
    text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
        deduplicate=True,
    )
    if not text or len(text.strip()) < 200:
        raise ArticleSummaryError("Unable to extract enough article text from the source URL")

    cleaned = text.strip()
    return ExtractedArticleContent(
        article_text=cleaned[: settings.SUMMARY_MAX_INPUT_CHARS],
        summary_input=cleaned[: settings.SUMMARY_MAX_INPUT_CHARS],
        content_excerpt=cleaned[: settings.SUMMARY_EXCERPT_CHARS],
        summary_source="trafilatura",
    )


def summarize_text(
    text: str,
    *,
    headline_title: str | None = None,
    article_description: str | None = None,
) -> str:
    """Pick the first N non-redundant sentences from trafilatura-cleaned text.

    News articles use the inverted pyramid — the most important facts are at
    the top — so lead-bias extraction gives consistently good results without
    needing a graph-based algorithm or external NLP models.
    """
    sentences = _split_sentences(text)
    if not sentences:
        raise ArticleSummaryError("Not enough sentence content to build a summary")

    filtered: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        key = _normalize_whitespace(sentence).lower()
        if key in seen:
            continue
        # Skip sentences that are essentially a restatement of the headline
        if headline_title and _similarity_ratio(sentence, headline_title) >= 0.75:
            continue
        seen.add(key)
        filtered.append(sentence)
        if len(filtered) >= settings.SUMMARY_SENTENCE_COUNT:
            break

    if not filtered:
        filtered = sentences[: settings.SUMMARY_SENTENCE_COUNT]

    return " ".join(filtered[: settings.SUMMARY_SENTENCE_COUNT])


def _headline_default_status(headline: dict[str, Any]) -> str:
    if headline.get("url") or headline.get("snippet"):
        return HEADLINE_STATUS_PENDING
    return HEADLINE_STATUS_FAILED


def initialize_headline_summary_fields(headlines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    initialized: list[dict[str, Any]] = []
    for headline in headlines:
        normalized = dict(headline)
        normalized.setdefault("snippet", None)
        normalized["summary"] = None
        normalized["summary_status"] = _headline_default_status(normalized)
        normalized["summary_error"] = None
        normalized["summary_source"] = None
        normalized["summary_generated_at"] = None
        normalized["content_excerpt"] = None
        if normalized["summary_status"] == HEADLINE_STATUS_FAILED:
            normalized["summary_error"] = "Headline does not contain a usable URL or snippet"
        initialized.append(normalized)
    return initialized


def reset_headline_summary_fields(headlines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped_headlines: list[dict[str, Any]] = []
    for headline in headlines:
        stripped_headlines.append(
            {key: value for key, value in dict(headline).items() if key not in _SUMMARY_HEADLINE_FIELDS}
        )
    return initialize_headline_summary_fields(stripped_headlines)


def _cache_key(url: str) -> str:
    return hashlib.sha256(f"{_SUMMARY_CACHE_VERSION}:{url}".encode("utf-8")).hexdigest()


def _get_cached_summary(db: Session, *, url: str) -> dict[str, Any] | None:
    cache = article_summary_cache_crud.get_cache_by_url_hash(db, url_hash=_cache_key(url))
    if cache is None:
        return None

    valid_after = _utc_now() - timedelta(seconds=settings.SUMMARY_CACHE_TTL_SECONDS)
    if cache.summary_generated_at < valid_after:
        return None

    return {
        "summary": cache.summary,
        "summary_status": HEADLINE_STATUS_COMPLETED,
        "summary_error": None,
        "summary_source": cache.summary_source,
        "summary_generated_at": cache.summary_generated_at.isoformat(),
        "content_excerpt": cache.content_excerpt,
    }


def _set_cached_summary(db: Session, *, url: str, payload: dict[str, Any]) -> None:
    generated_at_value = payload.get("summary_generated_at")
    if not isinstance(generated_at_value, str):
        raise ArticleSummaryError("Summary payload is missing generated timestamp")

    article_summary_cache_crud.upsert_summary_cache(
        db,
        url=url,
        url_hash=_cache_key(url),
        summary=str(payload.get("summary") or ""),
        content_excerpt=payload.get("content_excerpt"),
        summary_source=str(payload.get("summary_source") or "trafilatura"),
        summary_generated_at=datetime.fromisoformat(generated_at_value),
    )


def _build_fallback_payload(snippet: str) -> dict[str, Any]:
    normalized_snippet = _normalize_whitespace(snippet)
    if not normalized_snippet:
        raise ArticleSummaryError("Headline does not contain usable snippet fallback text")
    timestamp = _utc_now().isoformat()
    return {
        "summary": normalized_snippet,
        "summary_status": HEADLINE_STATUS_COMPLETED,
        "summary_error": None,
        "summary_source": "provider_snippet",
        "summary_generated_at": timestamp,
        "content_excerpt": normalized_snippet[: settings.SUMMARY_EXCERPT_CHARS],
    }


def summarize_headline(db: Session, headline: dict[str, Any]) -> dict[str, Any]:
    normalized_headline = dict(headline)
    url = str(normalized_headline.get("url") or "").strip()
    snippet = str(normalized_headline.get("snippet") or "").strip()
    title = str(normalized_headline.get("title") or "").strip()

    source = str(normalized_headline.get("source") or "unknown").strip()
    logger.info("  [%s] %s%s", source, title[:60], "…" if len(title) > 60 else "")

    if url:
        cached = _get_cached_summary(db, url=url)
        if cached is not None:
            logger.info("    → cache hit")
            return {**normalized_headline, **cached}

        logger.info("    → fetching: %s", url)
        try:
            html = _fetch_article_html(url)
            article_content = _extract_article_content(html, url=url, headline_title=title)
            timestamp = _utc_now().isoformat()
            summary_text = summarize_text(
                article_content.summary_input,
                headline_title=title,
                article_description=article_content.description or snippet,
            )
            payload = {
                "summary": summary_text,
                "summary_status": HEADLINE_STATUS_COMPLETED,
                "summary_error": None,
                "summary_source": article_content.summary_source,
                "summary_generated_at": timestamp,
                "content_excerpt": article_content.content_excerpt,
            }
            logger.info("    → summary OK (%d chars)", len(summary_text))
            _set_cached_summary(db, url=url, payload=payload)
            return {**normalized_headline, **payload}
        except (httpx.HTTPError, ArticleSummaryError) as exc:
            logger.warning("    → extraction failed (%s): %s", type(exc).__name__, exc)
            logger.warning("    → failed URL [%s]: %s", source, url)
            # Fall back to provider snippet when full-article extraction fails (e.g. paywalls)
            if snippet and (not title or _similarity_ratio(snippet, title) < 0.75):
                logger.info("    → using provider snippet as fallback")
                return {**normalized_headline, **_build_fallback_payload(snippet)}
            logger.info("    → no usable fallback, marking failed")
            return {
                **normalized_headline,
                "summary": None,
                "summary_status": HEADLINE_STATUS_FAILED,
                "summary_error": str(exc),
                "summary_source": None,
                "summary_generated_at": None,
                "content_excerpt": None,
            }

    if snippet and (not title or _similarity_ratio(snippet, title) < 0.75):
        logger.info("    → no URL, using snippet")
        return {**normalized_headline, **_build_fallback_payload(snippet)}

    logger.info("    → no URL or usable snippet, marking failed")
    return {
        **normalized_headline,
        "summary": None,
        "summary_status": HEADLINE_STATUS_FAILED,
        "summary_error": "Headline does not contain a usable URL or snippet distinct from the title",
        "summary_source": None,
        "summary_generated_at": None,
        "content_excerpt": None,
    }


def summarize_context_synchronous(db: Session, *, context: DailyContext) -> DailyContext:
    """Summarize all headlines for a context inline (blocking).

    Called during manual harvest so the frontend receives complete summaries
    immediately without needing background polling.
    """
    top_headlines = list(context.top_headlines or [])
    if not top_headlines:
        logger.info("[%s] No headlines to summarize", context.input_symbol)
        return context

    initialized = initialize_headline_summary_fields(top_headlines)
    logger.info("[%s] Summarizing %d headline(s)…", context.input_symbol, len(initialized))

    enriched: list[dict[str, Any]] = []
    for headline in initialized:
        enriched.append(summarize_headline(db, headline))

    completed = sum(1 for h in enriched if h.get("summary_status") == HEADLINE_STATUS_COMPLETED)
    final_status = _summary_status_for_headlines(enriched)
    logger.info(
        "[%s] Summary done — %d/%d succeeded (status=%s)",
        context.input_symbol, completed, len(enriched), final_status,
    )

    return daily_context_crud.update_headline_summaries(
        db,
        context=context,
        top_headlines=enriched,
        summary_status=final_status,
        summary_error=None if final_status != SUMMARY_STATUS_FAILED else "All headline summarization attempts failed",
        summary_completed_at=_utc_now(),
    )


def _summary_status_for_headlines(headlines: list[dict[str, Any]]) -> str:
    if not headlines:
        return SUMMARY_STATUS_NOT_AVAILABLE

    completed_count = sum(1 for h in headlines if h.get("summary_status") == HEADLINE_STATUS_COMPLETED)
    failed_count = sum(1 for h in headlines if h.get("summary_status") == HEADLINE_STATUS_FAILED)
    if completed_count and not failed_count:
        return SUMMARY_STATUS_COMPLETED
    if completed_count and failed_count:
        return SUMMARY_STATUS_PARTIAL
    return SUMMARY_STATUS_FAILED


def enqueue_daily_context_summary_job(db: Session, *, context: DailyContext) -> DailyContext:
    top_headlines = list(context.top_headlines or [])
    if not top_headlines:
        return daily_context_crud.update_summary_job(
            db,
            context=context,
            summary_status=SUMMARY_STATUS_NOT_AVAILABLE,
            summary_job_id=None,
            summary_error=None,
            summary_requested_at=None,
            summary_completed_at=_utc_now(),
        )

    queued_at = _utc_now()
    reset_headlines = reset_headline_summary_fields(top_headlines)
    job = summary_job_crud.upsert_summary_job(
        db,
        daily_context_id=context.id,
        status=SUMMARY_STATUS_QUEUED,
        queued_at=queued_at,
        started_at=None,
        completed_at=None,
        last_error=None,
        retry_count=0,
    )
    return daily_context_crud.update_summary_job(
        db,
        context=context,
        summary_status=SUMMARY_STATUS_QUEUED,
        summary_job_id=str(job.id),
        summary_error=None,
        summary_requested_at=queued_at,
        summary_completed_at=None,
        top_headlines=reset_headlines,
    )


def _build_job_result(*, context: DailyContext) -> dict[str, Any]:
    headlines = list(context.top_headlines or [])
    completed_count = sum(1 for h in headlines if h.get("summary_status") == HEADLINE_STATUS_COMPLETED)
    failed_count = sum(1 for h in headlines if h.get("summary_status") == HEADLINE_STATUS_FAILED)
    return {
        "context_id": str(context.id),
        "summary_status": context.summary_status,
        "completed_count": completed_count,
        "failed_count": failed_count,
    }


def process_summary_job(db: Session, *, job: SummaryJob) -> dict[str, Any]:
    context = daily_context_crud.get_daily_context_by_id(db, context_id=job.daily_context_id)
    if context is None:
        summary_job_crud.update_summary_job(
            db,
            job=job,
            status=SUMMARY_STATUS_FAILED,
            completed_at=_utc_now(),
            last_error="Daily context not found",
            retry_count=job.retry_count + 1,
        )
        raise ArticleSummaryError("Daily context not found")

    started_at = _utc_now()
    summary_job_crud.update_summary_job(
        db,
        job=job,
        status=SUMMARY_STATUS_PROCESSING,
        started_at=started_at,
        completed_at=None,
        last_error=None,
    )
    daily_context_crud.update_summary_job(
        db,
        context=context,
        summary_status=SUMMARY_STATUS_PROCESSING,
        summary_job_id=str(job.id),
        summary_error=None,
        summary_requested_at=context.summary_requested_at or started_at,
        summary_completed_at=None,
    )

    try:
        headlines = list(context.top_headlines or [])
        enriched_headlines = [summarize_headline(db, headline) for headline in headlines]
        final_status = _summary_status_for_headlines(enriched_headlines)
        completed_at = _utc_now()
        updated_context = daily_context_crud.update_headline_summaries(
            db,
            context=context,
            top_headlines=enriched_headlines,
            summary_status=final_status,
            summary_error=None if final_status != SUMMARY_STATUS_FAILED else "All headline summarization attempts failed",
            summary_completed_at=completed_at,
        )
        summary_job_crud.update_summary_job(
            db,
            job=job,
            status=final_status,
            started_at=started_at,
            completed_at=completed_at,
            last_error=updated_context.summary_error,
            retry_count=job.retry_count,
        )
        return _build_job_result(context=updated_context)
    except Exception as exc:
        completed_at = _utc_now()
        daily_context_crud.update_summary_job(
            db,
            context=context,
            summary_status=SUMMARY_STATUS_FAILED,
            summary_job_id=str(job.id),
            summary_error=str(exc),
            summary_requested_at=context.summary_requested_at or started_at,
            summary_completed_at=completed_at,
        )
        summary_job_crud.update_summary_job(
            db,
            job=job,
            status=SUMMARY_STATUS_FAILED,
            started_at=started_at,
            completed_at=completed_at,
            last_error=str(exc),
            retry_count=job.retry_count + 1,
        )
        raise


def process_pending_summary_jobs(db: Session, *, limit: int | None = None) -> int:
    jobs = summary_job_crud.list_summary_jobs_by_status(
        db,
        statuses=[SUMMARY_STATUS_QUEUED],
        limit=limit or settings.SUMMARY_WORKER_BATCH_SIZE,
    )

    processed_count = 0
    for job in jobs:
        try:
            process_summary_job(db, job=job)
        except Exception:
            logger.exception("Summary job %s failed", job.id)
        processed_count += 1
    return processed_count


def get_summary_task_status(db: Session, *, user_id, task_id: str) -> dict[str, Any]:
    try:
        job_id = uuid.UUID(task_id)
    except ValueError as exc:
        raise ArticleSummaryError("Invalid summary task id") from exc

    job = summary_job_crud.get_summary_job_by_id(db, job_id=job_id)
    if job is None:
        raise ArticleSummaryError("Summary task not found")

    context = daily_context_crud.get_daily_context_by_id(db, context_id=job.daily_context_id)
    if context is None or context.user_id != user_id:
        raise ArticleSummaryError("Summary task not found")

    status = job.status
    ready = status in {SUMMARY_STATUS_COMPLETED, SUMMARY_STATUS_PARTIAL, SUMMARY_STATUS_FAILED}
    successful = status in {SUMMARY_STATUS_COMPLETED, SUMMARY_STATUS_PARTIAL}
    failed = status == SUMMARY_STATUS_FAILED
    result = _build_job_result(context=context) if ready and successful else None

    return {
        "task_id": str(job.id),
        "status": status,
        "ready": ready,
        "successful": successful,
        "failed": failed,
        "result": result,
        "error": job.last_error,
    }
