import email.utils
from datetime import date, datetime, timedelta, timezone
from html import unescape
import re
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.services.marketaux_service import _company_name_variants, _contains_company_name_variant, _normalize_whitespace


class GoogleNewsError(RuntimeError):
    pass


def _query_for_company(company_name: str, target_date: date | None) -> str:
    variants = [f'"{variant}"' for variant in _company_name_variants(company_name)[:2]]
    query = " OR ".join(variants) if variants else f'"{company_name}"'

    if target_date is not None:
        start_date = target_date - timedelta(days=2)
        end_date = target_date + timedelta(days=1)
        query += f" after:{start_date.isoformat()} before:{end_date.isoformat()}"
    else:
        query += f" when:{settings.GOOGLE_NEWS_LOOKBACK_DAYS}d"
    return query


def _extract_description_text(description_html: str | None) -> str | None:
    if not description_html:
        return None
    soup = BeautifulSoup(unescape(description_html), "html.parser")
    text = _normalize_whitespace(soup.get_text(" ", strip=True))
    return text or None


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


def _resolve_google_link(url: str | None) -> str | None:
    if not url:
        return None
    try:
        with httpx.Client(follow_redirects=True, timeout=10.0) as client:
            response = client.get(url)
            final_url = str(response.url)
            return final_url or url
    except Exception:
        return url


def _article_in_window(article: dict[str, Any], target_date: date | None) -> bool:
    if target_date is None:
        return True
    published_at = article.get("published_at")
    if not published_at:
        return True
    try:
        parsed = datetime.fromisoformat(str(published_at))
    except ValueError:
        return True
    return target_date - timedelta(days=2) <= parsed.date() <= target_date


def _normalize_title(title: str) -> str:
    cleaned_title = _normalize_whitespace(title)
    cleaned_title = re.sub(r"\s*-\s*[^-]+$", "", cleaned_title)
    return cleaned_title


def fetch_company_news(
    company_name: str,
    *,
    target_date: date | None = None,
    article_limit: int | None = None,
) -> list[dict[str, Any]]:
    query = _query_for_company(company_name, target_date)
    params = {
        "q": query,
        "hl": settings.GOOGLE_NEWS_HL,
        "gl": settings.GOOGLE_NEWS_GL,
        "ceid": settings.GOOGLE_NEWS_CEID,
    }

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(settings.GOOGLE_NEWS_RSS_BASE_URL, params=params)
            response.raise_for_status()
            rss_content = response.text
    except httpx.HTTPError as exc:
        raise GoogleNewsError("Google News RSS request failed") from exc

    try:
        root = ET.fromstring(rss_content)
    except ET.ParseError as exc:
        raise GoogleNewsError("Google News RSS returned invalid XML") from exc

    articles: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    max_items = max(settings.GOOGLE_NEWS_REQUEST_LIMIT, article_limit or settings.DAILY_CONTEXT_ARTICLE_LIMIT)

    for item in root.findall(".//item"):
        raw_title = item.findtext("title") or ""
        raw_link = item.findtext("link")
        source_node = item.find("source")
        description_html = item.findtext("description")
        article = {
            "title": _normalize_title(raw_title),
            "url": _resolve_google_link(raw_link),
            "source": source_node.text.strip() if source_node is not None and source_node.text else None,
            "published_at": _parse_pub_date(item.findtext("pubDate")),
            "snippet": _extract_description_text(description_html),
        }

        if not article["url"] or article["url"] in seen_urls:
            continue
        if not article["title"]:
            continue
        if not any(
            _contains_company_name_variant(str(article.get(field) or ""), company_name)
            for field in ("title", "snippet")
        ):
            continue
        if not _article_in_window(article, target_date):
            continue

        seen_urls.add(str(article["url"]))
        articles.append(article)
        if len(articles) >= max_items:
            break

    return articles[: article_limit or settings.DAILY_CONTEXT_ARTICLE_LIMIT]
