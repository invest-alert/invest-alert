import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
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
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "will",
    "with",
}

_SUMMARY_HEADLINE_FIELDS = {
    "summary",
    "summary_status",
    "summary_error",
    "summary_source",
    "summary_generated_at",
    "content_excerpt",
}

_SUMMARY_CACHE_VERSION = "v2"

_JSON_LD_ARTICLE_TYPES = {"ARTICLE", "NEWSARTICLE", "REPORTAGENEWSARTICLE"}

_DOMAIN_SELECTORS: dict[str, list[str]] = {
    "economictimes.indiatimes.com": [
        "article .paywall",
        "article",
        "main article",
    ],
    "thehindubusinessline.com": [
        "[itemprop='articleBody']",
        "article",
        "main article",
    ],
}

_STOP_SECTION_MARKERS = [
    "read more news on",
    "catch all the",
    "subscribe to et prime",
    "add comment",
    "lessons from the grandmasters",
    "recommended stories",
    "related stories",
    "follow us on",
    "share this article",
    "more like this",
    "also read",
]

_NOISE_LINE_PATTERNS = [
    re.compile(r"^synopsis$", re.IGNORECASE),
    re.compile(r"^et online$", re.IGNORECASE),
    re.compile(r"^add now!?$", re.IGNORECASE),
    re.compile(r"^watch now$", re.IGNORECASE),
    re.compile(r"^add comment$", re.IGNORECASE),
    re.compile(r"^read more news on$", re.IGNORECASE),
    re.compile(r"^subscribe to .*$", re.IGNORECASE),
    re.compile(r"^catch all the .*$", re.IGNORECASE),
    re.compile(r"^lessons from the grandmasters$", re.IGNORECASE),
    re.compile(r"^published on .*$", re.IGNORECASE),
    re.compile(r"^updated on .*$", re.IGNORECASE),
]

_NOISE_NODE_SELECTORS = [
    ".ad",
    ".ads",
    ".advertisement",
    ".social-share",
    ".share",
    ".related",
    ".subscription",
    ".subscribe",
    ".comments",
    ".comment",
    ".taboola",
    ".OUTBRAIN",
    ".newsletter",
    ".premium",
    ".promo",
    ".story-share",
    ".article-social",
]


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


def _url_host(url: str) -> str:
    return urlparse(url).netloc.lower()


def _iter_json_ld_items(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        graph = payload.get("@graph")
        if isinstance(graph, list):
            for entry in graph:
                items.extend(_iter_json_ld_items(entry))
        items.append(payload)
    elif isinstance(payload, list):
        for entry in payload:
            items.extend(_iter_json_ld_items(entry))
    return items


def _extract_structured_article_fields(soup: BeautifulSoup) -> dict[str, str | None]:
    best_item: dict[str, Any] | None = None
    best_body_length = 0

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_payload = script.string or script.get_text()
        if not raw_payload or not raw_payload.strip():
            continue
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue

        for item in _iter_json_ld_items(payload):
            article_type = item.get("@type")
            if isinstance(article_type, list):
                normalized_types = {str(value).upper() for value in article_type}
            else:
                normalized_types = {str(article_type).upper()}
            if not normalized_types.intersection(_JSON_LD_ARTICLE_TYPES):
                continue

            article_body = _normalize_whitespace(str(item.get("articleBody") or ""))
            if len(article_body) > best_body_length:
                best_item = item
                best_body_length = len(article_body)

    if best_item is None:
        return {"headline": None, "description": None, "article_body": None}

    return {
        "headline": _normalize_whitespace(str(best_item.get("headline") or "")) or None,
        "description": _normalize_whitespace(str(best_item.get("description") or "")) or None,
        "article_body": _normalize_whitespace(str(best_item.get("articleBody") or "")) or None,
    }


def _extract_meta_description(soup: BeautifulSoup) -> str | None:
    for attr_name, attr_value in (
        ("name", "description"),
        ("property", "og:description"),
        ("name", "twitter:description"),
    ):
        meta = soup.find("meta", attrs={attr_name: attr_value})
        if meta is None:
            continue
        content = _normalize_whitespace(str(meta.get("content") or ""))
        if content:
            return content
    return None


def _remove_noise_nodes(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "svg"]):
        tag.decompose()
    for selector in _NOISE_NODE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()


def _truncate_at_stop_marker(text: str) -> str:
    truncated_text = text
    lower_text = truncated_text.lower()
    for marker in _STOP_SECTION_MARKERS:
        marker_index = lower_text.find(marker)
        if marker_index != -1:
            truncated_text = truncated_text[:marker_index]
            lower_text = truncated_text.lower()
    return truncated_text


def _looks_like_tabular_noise(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return True
    if re.search(r"\bRank\s+Bank\s+FY\d{2}", normalized, re.IGNORECASE):
        return True

    tokens = normalized.split()
    numeric_tokens = sum(
        1
        for token in tokens
        if re.fullmatch(r"[₹$]?\d[\d,]*(?:\.\d+)?[%]?", token)
    )
    alpha_tokens = sum(1 for token in tokens if re.search(r"[A-Za-z]", token))
    if len(tokens) >= 8 and numeric_tokens >= max(4, len(tokens) // 2) and alpha_tokens <= numeric_tokens + 2:
        return True
    return False


def _looks_like_noise_line(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return True
    if _looks_like_tabular_noise(normalized):
        return True
    return any(pattern.match(normalized) for pattern in _NOISE_LINE_PATTERNS)


def _clean_article_text(text: str) -> str:
    normalized = _truncate_at_stop_marker(text)
    normalized = normalized.replace("\u00a0", " ")
    normalized = normalized.replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"([.!?][\"”']?)(?=[A-Z])", r"\1 ", normalized)
    normalized = re.sub(r"\n+", "\n", normalized)

    # Restore some paragraph boundaries before cleaning individual blocks.
    normalized = re.sub(r"(?<=[.!?])\s+(?=[A-Z][a-z])", "\n", normalized)
    blocks = [block.strip(" -") for block in normalized.split("\n")]

    cleaned_blocks: list[str] = []
    seen_blocks: set[str] = set()
    for block in blocks:
        block = _normalize_whitespace(block)
        if not block or _looks_like_noise_line(block):
            continue
        if len(block) < 25 and not re.search(r"[.!?]$", block):
            continue
        if block.lower() in seen_blocks:
            continue
        seen_blocks.add(block.lower())
        cleaned_blocks.append(block)

    cleaned_text = "\n".join(cleaned_blocks)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()
    return cleaned_text


def _extract_candidate_text(soup: BeautifulSoup, selector: str | None = None) -> str:
    node = soup.select_one(selector) if selector else soup.body
    if node is None:
        return ""

    paragraphs: list[str] = []
    for tag in node.find_all(["p", "li", "h2", "h3", "blockquote"]):
        text = _normalize_whitespace(tag.get_text(" ", strip=True))
        if len(text) >= 40:
            paragraphs.append(text)

    deduped_paragraphs: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        lowered = paragraph.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped_paragraphs.append(paragraph)
    return "\n".join(deduped_paragraphs)


def _extract_dom_article_text(soup: BeautifulSoup, url: str) -> tuple[str, str]:
    host = _url_host(url)
    selectors = _DOMAIN_SELECTORS.get(host, []) + [
        "article",
        "main",
        "[role='main']",
        "[itemprop='articleBody']",
        ".article-body",
        ".story-body",
        ".article__body",
        ".content",
    ]

    candidate_texts: list[tuple[str, str]] = []
    for selector in selectors:
        text = _extract_candidate_text(soup, selector)
        if text:
            if len(_clean_article_text(text)) >= 200:
                return text, f"article_dom:{selector}"
            candidate_texts.append((selector, text))
    page_text = _extract_candidate_text(soup)
    if page_text:
        candidate_texts.append(("body", page_text))

    if not candidate_texts:
        return "", "article_dom"

    selector, best_text = max(candidate_texts, key=lambda item: len(item[1]))
    return best_text, f"article_dom:{selector}"


def _sentence_overlap(sentence: str, keywords: set[str]) -> int:
    if not keywords:
        return 0
    return len(set(_sentence_words(sentence)).intersection(keywords))


def _similarity_ratio(sentence: str, reference: str) -> float:
    """Returns the fraction of sentence keywords that also appear in reference.
    A ratio >= 0.75 means the sentence is essentially a restatement of the reference."""
    sentence_words = set(_sentence_words(sentence))
    reference_words = set(_sentence_words(reference))
    if not sentence_words or not reference_words:
        return 0.0
    return len(sentence_words & reference_words) / len(sentence_words)


def _build_summary_input_text(
    article_text: str, *, description: str | None = None, headline_title: str | None = None
) -> str:
    lead_sentences = []
    for sentence in _split_sentences(article_text):
        if _looks_like_noise_line(sentence):
            continue
        # Skip sentences that are essentially a restatement of the headline
        if headline_title and _similarity_ratio(sentence, headline_title) >= 0.75:
            continue
        lead_sentences.append(sentence)
        if len(lead_sentences) >= max(settings.SUMMARY_SENTENCE_COUNT + 3, 6):
            break

    if description:
        for description_sentence in _split_sentences(description)[:1]:
            normalized_description = _normalize_whitespace(description_sentence)
            if not normalized_description:
                continue
            if any(normalized_description.lower() == sentence.lower() for sentence in lead_sentences):
                continue
            # Don't prepend description if it's too close to the headline title
            if headline_title and _similarity_ratio(normalized_description, headline_title) >= 0.70:
                continue
            lead_sentences.insert(0, normalized_description)

    if not lead_sentences:
        raise ArticleSummaryError("Unable to build a clean summary input from the article")

    return " ".join(lead_sentences)


def _extract_article_content(html: str, *, url: str, headline_title: str | None = None) -> ExtractedArticleContent:
    soup = BeautifulSoup(html, "html.parser")
    structured_fields = _extract_structured_article_fields(soup)
    meta_description = _extract_meta_description(soup)

    structured_article_body = structured_fields.get("article_body")
    structured_description = structured_fields.get("description") or meta_description
    if structured_article_body:
        article_text = _clean_article_text(structured_article_body)
        if len(article_text) >= 200:
            summary_input = _build_summary_input_text(
                article_text, description=structured_description, headline_title=headline_title
            )
            return ExtractedArticleContent(
                article_text=article_text[: settings.SUMMARY_MAX_INPUT_CHARS],
                summary_input=summary_input[: settings.SUMMARY_MAX_INPUT_CHARS],
                content_excerpt=summary_input[: settings.SUMMARY_EXCERPT_CHARS],
                summary_source="article_jsonld",
                description=structured_description,
            )

    _remove_noise_nodes(soup)
    dom_text, dom_source = _extract_dom_article_text(soup, url)
    article_text = _clean_article_text(dom_text)
    if len(article_text) < 200:
        raise ArticleSummaryError("Unable to extract enough article text from the source URL")

    summary_input = _build_summary_input_text(
        article_text, description=structured_description, headline_title=headline_title
    )
    return ExtractedArticleContent(
        article_text=article_text[: settings.SUMMARY_MAX_INPUT_CHARS],
        summary_input=summary_input[: settings.SUMMARY_MAX_INPUT_CHARS],
        content_excerpt=summary_input[: settings.SUMMARY_EXCERPT_CHARS],
        summary_source=dom_source,
        description=structured_description,
    )


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
        summary_source=str(payload.get("summary_source") or "article_text"),
        summary_generated_at=datetime.fromisoformat(generated_at_value),
    )


def _fetch_article_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
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


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", _normalize_whitespace(text))
    return [sentence.strip() for sentence in sentences if len(sentence.strip().split()) >= 6]


def _sentence_words(sentence: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{1,}", sentence.lower())
        if token not in _STOP_WORDS
    ]


def _keyword_set(text: str | None) -> set[str]:
    if not text:
        return set()
    return {word for word in _sentence_words(text) if len(word) > 2}


def summarize_text(
    text: str,
    *,
    headline_title: str | None = None,
    article_description: str | None = None,
) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        raise ArticleSummaryError("Not enough sentence content to build a summary")
    deduped_sentences: list[str] = []
    seen_sentences: set[str] = set()
    headline_keywords = _keyword_set(headline_title)
    description_keywords = _keyword_set(article_description)

    for sentence in sentences:
        normalized_sentence = _normalize_whitespace(sentence).lower()
        if normalized_sentence in seen_sentences:
            continue
        if len(sentence.split()) < 7:
            continue
        # Skip sentences that are essentially a restatement of the headline title
        if headline_title and _similarity_ratio(sentence, headline_title) >= 0.75:
            continue
        overlap = _sentence_overlap(sentence, headline_keywords) + _sentence_overlap(sentence, description_keywords)
        if len(deduped_sentences) >= settings.SUMMARY_SENTENCE_COUNT and overlap <= 0:
            continue
        seen_sentences.add(normalized_sentence)
        deduped_sentences.append(sentence)
        if len(deduped_sentences) >= settings.SUMMARY_SENTENCE_COUNT:
            break

    if not deduped_sentences:
        deduped_sentences = sentences[: settings.SUMMARY_SENTENCE_COUNT]
    return " ".join(deduped_sentences[: settings.SUMMARY_SENTENCE_COUNT])


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

    if url:
        cached = _get_cached_summary(db, url=url)
        if cached is not None:
            return {**normalized_headline, **cached}

        try:
            html = _fetch_article_html(url)
            article_content = _extract_article_content(html, url=url, headline_title=title)
            timestamp = _utc_now().isoformat()
            payload = {
                "summary": summarize_text(
                    article_content.summary_input,
                    headline_title=title,
                    article_description=article_content.description or snippet,
                ),
                "summary_status": HEADLINE_STATUS_COMPLETED,
                "summary_error": None,
                "summary_source": article_content.summary_source,
                "summary_generated_at": timestamp,
                "content_excerpt": article_content.content_excerpt,
            }
            _set_cached_summary(db, url=url, payload=payload)
            return {**normalized_headline, **payload}
        except (httpx.HTTPError, ArticleSummaryError) as exc:
            logger.warning("Article summarization failed for %s: %s", url, exc)
            if snippet and (not title or _similarity_ratio(snippet, title) < 0.75):
                return {**normalized_headline, **_build_fallback_payload(snippet)}
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
        return {**normalized_headline, **_build_fallback_payload(snippet)}

    return {
        **normalized_headline,
        "summary": None,
        "summary_status": HEADLINE_STATUS_FAILED,
        "summary_error": "Headline does not contain a usable URL or snippet distinct from the title",
        "summary_source": None,
        "summary_generated_at": None,
        "content_excerpt": None,
    }


def _summary_status_for_headlines(headlines: list[dict[str, Any]]) -> str:
    if not headlines:
        return SUMMARY_STATUS_NOT_AVAILABLE

    completed_count = sum(1 for headline in headlines if headline.get("summary_status") == HEADLINE_STATUS_COMPLETED)
    failed_count = sum(1 for headline in headlines if headline.get("summary_status") == HEADLINE_STATUS_FAILED)
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
    completed_count = sum(
        1 for headline in headlines if headline.get("summary_status") == HEADLINE_STATUS_COMPLETED
    )
    failed_count = sum(
        1 for headline in headlines if headline.get("summary_status") == HEADLINE_STATUS_FAILED
    )
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
