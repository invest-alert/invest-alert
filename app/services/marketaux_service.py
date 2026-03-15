import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.core.config import settings


class MarketauxError(RuntimeError):
    pass


@dataclass
class ResolvedEquity:
    symbol: str
    company_name: str


def _normalize_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _company_name_variants(company_name: str) -> list[str]:
    normalized_company_name = _normalize_whitespace(company_name)
    if not normalized_company_name:
        return []

    variants = [normalized_company_name]
    stripped = re.sub(
        r"\b(LIMITED|LTD|LTD\.|INC|INCORPORATED|PLC|CORP|CORPORATION)\b\.?$",
        "",
        normalized_company_name,
        flags=re.IGNORECASE,
    )
    stripped = _normalize_whitespace(stripped)
    if stripped and stripped not in variants:
        variants.append(stripped)
    return variants


def _contains_company_name_variant(value: str, company_name: str) -> bool:
    normalized_value = _normalize_text(value)
    if not normalized_value:
        return False

    for variant in _company_name_variants(company_name):
        normalized_variant = _normalize_text(variant)
        if normalized_variant and f" {normalized_variant} " in f" {normalized_value} ":
            return True
    return False


def is_marketaux_configured() -> bool:
    return bool(settings.MARKETAUX_API_KEY)


def _request(path: str, params: dict[str, Any]) -> dict[str, Any]:
    if not is_marketaux_configured():
        raise MarketauxError("MARKETAUX_API_KEY is not configured")

    request_params = {
        **params,
        "api_token": settings.MARKETAUX_API_KEY,
    }
    with httpx.Client(base_url=settings.MARKETAUX_BASE_URL, timeout=20.0) as client:
        response = client.get(path, params=request_params)
        response.raise_for_status()
        return response.json()


def _marketaux_error_message(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    if response is None:
        return "Marketaux request failed"
    try:
        payload = response.json()
    except ValueError:
        payload = None

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return message
    return f"Marketaux request failed with status {response.status_code}"


def _request_news_payload(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _request("/news/all", params)
    except httpx.HTTPStatusError as exc:
        response = exc.response
        status_code = response.status_code if response is not None else None
        if params.get("symbols") and status_code in {400, 402}:
            fallback_params = dict(params)
            fallback_params.pop("symbols", None)
            try:
                return _request("/news/all", fallback_params)
            except httpx.HTTPStatusError as fallback_exc:
                raise MarketauxError(_marketaux_error_message(fallback_exc)) from fallback_exc
        raise MarketauxError(_marketaux_error_message(exc)) from exc


def _candidate_score(candidate: dict[str, Any], query: str, exchange: str) -> int:
    normalized_query = _normalize_text(query)
    candidate_name = _normalize_text(str(candidate.get("name") or ""))
    candidate_symbol = _normalize_text(str(candidate.get("symbol") or ""))
    candidate_exchange = _normalize_text(
        " ".join(
            str(candidate.get(key) or "")
            for key in ("exchange", "exchange_long", "exchange_name")
        )
    )
    candidate_country = _normalize_text(
        " ".join(
            str(candidate.get(key) or "")
            for key in ("country", "country_code", "country_name")
        )
    )

    score = 0
    if normalized_query == candidate_name:
        score += 50
    if normalized_query == candidate_symbol:
        score += 40
    if normalized_query and normalized_query in candidate_name:
        score += 20
    if exchange and _normalize_text(exchange) in candidate_exchange:
        score += 20
    if "INDIA" in candidate_country or candidate_country == "IN":
        score += 15
    return score


def resolve_equity(query: str, exchange: str) -> ResolvedEquity | None:
    if not is_marketaux_configured():
        return None

    try:
        payload = _request(
            "/entity/search/",
            {
                "search": query,
                "countries": settings.MARKETAUX_NEWS_COUNTRIES,
                "types": "equity",
            },
        )
    except httpx.HTTPStatusError as exc:
        raise MarketauxError(_marketaux_error_message(exc)) from exc
    candidates = payload.get("data") or []
    if not candidates:
        return None

    best_candidate = max(candidates, key=lambda candidate: _candidate_score(candidate, query, exchange))
    symbol = str(best_candidate.get("symbol") or "").strip().upper()
    company_name = str(best_candidate.get("name") or query).strip()
    if not symbol:
        return None
    return ResolvedEquity(symbol=symbol, company_name=company_name)


def article_mentions_company(article: dict[str, Any], company_name: str) -> bool:
    searchable_fields = [
        str(article.get("title") or ""),
        str(article.get("description") or ""),
        str(article.get("snippet") or ""),
    ]
    if any(_contains_company_name_variant(field, company_name) for field in searchable_fields):
        return True

    entities = article.get("entities") or []
    company_variants = {_normalize_text(value) for value in _company_name_variants(company_name)}
    for entity in entities:
        entity_variants = {_normalize_text(value) for value in _company_name_variants(str(entity.get("name") or ""))}
        if company_variants.intersection(entity_variants):
            return True

    return False


def _article_relevance_score(article: dict[str, Any], company_name: str) -> int:
    score = 0
    title = str(article.get("title") or "")
    description = str(article.get("description") or "")
    snippet = str(article.get("snippet") or "")

    if _contains_company_name_variant(title, company_name):
        score += 60
    if _contains_company_name_variant(description, company_name):
        score += 35
    if _contains_company_name_variant(snippet, company_name):
        score += 25

    entities = article.get("entities") or []
    company_variants = {_normalize_text(value) for value in _company_name_variants(company_name)}
    if any(company_variants.intersection({_normalize_text(value) for value in _company_name_variants(str(entity.get("name") or ""))}) for entity in entities):
        score += 20

    return score


def _normalize_article(article: dict[str, Any]) -> dict[str, Any]:
    source = article.get("source")
    if isinstance(source, dict):
        source_name = source.get("name")
    else:
        source_name = source

    return {
        "title": str(article.get("title") or "").strip(),
        "url": article.get("url"),
        "source": source_name,
        "published_at": article.get("published_at") or article.get("published_on"),
        "snippet": _normalize_whitespace(
            " ".join(str(article.get(field) or "") for field in ("description", "snippet"))
        )
        or None,
    }


def filter_articles_for_company(
    articles: list[dict[str, Any]],
    company_name: str,
    *,
    article_limit: int,
) -> list[dict[str, Any]]:
    filtered_articles: list[tuple[int, int, dict[str, Any]]] = []
    seen_keys: set[str] = set()

    for index, article in enumerate(articles):
        if not article_mentions_company(article, company_name):
            continue

        relevance_score = _article_relevance_score(article, company_name)
        if relevance_score <= 0:
            continue

        normalized_article = _normalize_article(article)
        dedupe_key = str(normalized_article.get("url") or normalized_article.get("title")).strip().lower()
        if not dedupe_key or dedupe_key in seen_keys:
            continue

        seen_keys.add(dedupe_key)
        filtered_articles.append((relevance_score, index, normalized_article))

    ranked_articles = [
        article
        for _, _, article in sorted(filtered_articles, key=lambda item: (-item[0], item[1]))
    ]
    return ranked_articles[:article_limit]


def fetch_company_news(
    company_name: str,
    *,
    market_symbol: str | None = None,
    target_date: date | None = None,
    article_limit: int | None = None,
) -> list[dict[str, Any]]:
    request_limit = max(settings.MARKETAUX_NEWS_LIMIT, article_limit or settings.DAILY_CONTEXT_ARTICLE_LIMIT)
    base_params: dict[str, Any] = {
        "search": f"\"{company_name}\"",
        "countries": settings.MARKETAUX_NEWS_COUNTRIES,
        "language": settings.MARKETAUX_NEWS_LANGUAGE,
        "limit": request_limit,
    }
    if market_symbol:
        base_params["symbols"] = market_symbol

    request_params_list: list[dict[str, Any]] = []
    if target_date is not None:
        for lookback_days in range(0, 3):
            lookup_date = target_date - timedelta(days=lookback_days)
            request_params_list.append(
                {
                    **base_params,
                    "published_after": datetime.combine(lookup_date, datetime.min.time()).isoformat(),
                }
            )
    else:
        request_params_list.append(base_params)

    for params in request_params_list:
        payload = _request_news_payload(params)
        articles = payload.get("data") or []
        filtered_articles = filter_articles_for_company(
            articles,
            company_name,
            article_limit=article_limit or settings.DAILY_CONTEXT_ARTICLE_LIMIT,
        )
        if filtered_articles:
            return filtered_articles

    return []
