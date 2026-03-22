"""Indian financial news fetched directly from trusted source RSS feeds.

Each feed returns real article URLs (no Google News proxy wrapper), so
trafilatura can extract article text for summarisation without any URL
decoding step.

Feed registry (hardcoded — these feeds are stable):
  BusinessLine  – markets + companies sections
  Economic Times – default feed
  Moneycontrol  – latest news
  CNBCTV18      – market + business feeds
  LiveMint      – markets + companies sections
  NDTV Profit   – latest feed

Fetching is done in parallel (one thread per feed).  Articles are filtered
by company-name variant match (same algorithm as marketaux_service), then
deduplicated by URL and optionally narrowed to a date window.
"""

import email.utils
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


# Words too generic to be useful as standalone match signals.
# Stripping these from company names before matching prevents noise
# (e.g. "bank" alone matching every banking article).
_STRIP_WORDS: frozenset[str] = frozenset({
    "limited", "ltd", "pvt", "private", "corporation", "corp", "inc",
    "company", "co", "and", "of", "the", "for", "a", "an",
})


def _contains_company_name_variant(text: str, company_name: str) -> bool:
    """Return True only when *text* is clearly about *company_name*.

    Strategy:
    1. Fast path: full company name is a substring of text.
    2. Tokenise the name, drop generic suffix/connector words and tokens
       shorter than 3 chars, then require ALL remaining tokens to be present
       (AND logic).  This prevents single common words like 'bank' or
       'industries' from matching unrelated articles.
    """
    text_lower = text.lower()
    name_lower = company_name.lower()

    # Full name match (most reliable)
    if name_lower in text_lower:
        return True

    # Build meaningful token list
    tokens = [
        t for t in re.split(r"[\s,.()\-&/]+", name_lower)
        if t and len(t) >= 3 and t not in _STRIP_WORDS
    ]

    if not tokens:
        # Fallback for very short / all-generic names: any token ≥ 4 chars
        fallback = [t for t in re.split(r"[\s,.()\-&/]+", name_lower) if len(t) >= 4]
        return any(t in text_lower for t in fallback)

    # ALL meaningful tokens must appear (AND logic — precision over recall)
    return all(token in text_lower for token in tokens)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feed registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _FeedDef:
    url: str
    source: str


_FEED_REGISTRY: list[_FeedDef] = [
    _FeedDef("https://www.thehindubusinessline.com/markets/feeder/default.rss",   "BusinessLine"),
    _FeedDef("https://www.thehindubusinessline.com/companies/feeder/default.rss", "BusinessLine"),
    _FeedDef("https://economictimes.indiatimes.com/rssFeedsDefault.cms",          "Economic Times"),
    _FeedDef("https://www.moneycontrol.com/rss/latestnews.xml",                   "Moneycontrol"),
    _FeedDef("https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",        "CNBCTV18"),
    _FeedDef("https://www.cnbctv18.com/commonfeeds/v1/cne/rss/business.xml",      "CNBCTV18"),
    _FeedDef("https://www.livemint.com/rss/markets",                              "LiveMint"),
    _FeedDef("https://www.livemint.com/rss/companies",                            "LiveMint"),
    _FeedDef("https://feeds.feedburner.com/ndtvprofit-latest",                    "NDTV Profit"),
]

_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

_MAX_FEED_WORKERS = 5


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_pub_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _pub_date_obj(value: str | None) -> datetime | None:
    """Return a timezone-aware datetime or None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _extract_snippet(description_html: str | None) -> str | None:
    if not description_html:
        return None
    soup = BeautifulSoup(unescape(description_html), "html.parser")
    text = _normalize_whitespace(soup.get_text(" ", strip=True))
    return text or None


def _normalize_title(title: str) -> str:
    cleaned = _normalize_whitespace(title)
    # Strip trailing source tag like "- BusinessLine" or "| CNBCTV18"
    cleaned = re.sub(r"\s*[-|]\s*[^-|]+$", "", cleaned)
    return cleaned.strip()


def _article_in_window(article: dict[str, Any], target_date: date | None) -> bool:
    """Return True when the article falls within the acceptable date range."""
    if target_date is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.NEWS_LOOKBACK_DAYS)
        pub = _pub_date_obj(article.get("published_at"))
        if pub is None:
            return True          # no date → include by default
        return pub >= cutoff

    pub = _pub_date_obj(article.get("published_at"))
    if pub is None:
        return True
    return target_date - timedelta(days=2) <= pub.date() <= target_date


# ---------------------------------------------------------------------------
# Per-feed fetching
# ---------------------------------------------------------------------------

def _fetch_feed(feed: _FeedDef) -> list[dict[str, Any]]:
    """Fetch one RSS feed and return raw parsed article dicts."""
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers=_REQUEST_HEADERS) as client:
            response = client.get(feed.url)
            response.raise_for_status()
            rss_text = response.text
    except httpx.HTTPError as exc:
        logger.debug("Feed fetch failed [%s]: %s", feed.source, exc)
        return []

    try:
        root = ET.fromstring(rss_text)
    except ET.ParseError as exc:
        logger.debug("Feed XML invalid [%s]: %s", feed.source, exc)
        return []

    articles: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = _normalize_title(item.findtext("title") or "")
        url   = item.findtext("link") or ""
        pub   = _parse_pub_date(item.findtext("pubDate"))
        snip  = _extract_snippet(item.findtext("description"))

        # Skip items that still point back to Google News (shouldn't happen
        # with direct feeds, but guard just in case)
        if not url or "news.google.com" in url:
            continue
        if not title:
            continue

        articles.append({
            "title":        title,
            "url":          url,
            "source":       feed.source,
            "published_at": pub,
            "snippet":      snip,
        })

    logger.debug("Feed [%s] → %d raw items (%s)", feed.source, len(articles), feed.url)
    return articles


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_company_news(
    company_name: str,
    *,
    target_date: date | None = None,
    article_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch news articles about *company_name* from Indian financial RSS feeds.

    Drop-in replacement for the old google_news_service in daily_context_service.

    Strategy:
      1. Fetch all feeds in parallel (thread pool).
      2. Filter by company-name variant match (title OR snippet).
      3. Filter by date window (target_date ± 2 days, or last LOOKBACK_DAYS).
      4. Deduplicate by URL.
      5. Sort newest-first, return up to *article_limit*.
    """
    limit = article_limit or settings.DAILY_CONTEXT_ARTICLE_LIMIT

    # --- Step 1: parallel feed fetch ---
    all_articles: list[dict[str, Any]] = []
    workers = min(_MAX_FEED_WORKERS, len(_FEED_REGISTRY))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_feed, feed): feed for feed in _FEED_REGISTRY}
        for future in as_completed(futures):
            feed = futures[future]
            try:
                all_articles.extend(future.result())
            except Exception:
                logger.exception("Unexpected error fetching feed [%s]", feed.source)

    logger.debug("Total raw articles across all feeds: %d", len(all_articles))

    # --- Step 2 & 3: filter by company name + date ---
    filtered: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for article in all_articles:
        url = article["url"]
        if url in seen_urls:
            continue

        # Company-name relevance check
        if not any(
            _contains_company_name_variant(str(article.get(field) or ""), company_name)
            for field in ("title", "snippet")
        ):
            continue

        # Date window check
        if not _article_in_window(article, target_date):
            continue

        seen_urls.add(url)
        filtered.append(article)

    # --- Step 4: sort newest-first ---
    def _sort_key(a: dict[str, Any]) -> datetime:
        dt = _pub_date_obj(a.get("published_at"))
        return dt if dt is not None else datetime.min.replace(tzinfo=timezone.utc)

    filtered.sort(key=_sort_key, reverse=True)

    logger.info(
        "indian_financial_news: company=%r, target_date=%s → %d matched (limit=%d)",
        company_name, target_date, len(filtered), limit,
    )

    return filtered[:limit]
