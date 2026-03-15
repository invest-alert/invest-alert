from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article_summary_cache import ArticleSummaryCache


def get_cache_by_url_hash(
    db: Session,
    *,
    url_hash: str,
) -> ArticleSummaryCache | None:
    return db.scalar(select(ArticleSummaryCache).where(ArticleSummaryCache.url_hash == url_hash))


def upsert_summary_cache(
    db: Session,
    *,
    url: str,
    url_hash: str,
    summary: str,
    content_excerpt: str | None,
    summary_source: str,
    summary_generated_at: datetime,
) -> ArticleSummaryCache:
    cache = get_cache_by_url_hash(db, url_hash=url_hash)
    if cache is None:
        cache = ArticleSummaryCache(url_hash=url_hash)
        db.add(cache)

    cache.url = url
    cache.summary = summary
    cache.content_excerpt = content_excerpt
    cache.summary_source = summary_source
    cache.summary_generated_at = summary_generated_at

    db.commit()
    db.refresh(cache)
    return cache
