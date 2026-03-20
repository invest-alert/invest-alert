import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import yfinance as yf


class MarketPriceError(RuntimeError):
    pass


@dataclass
class PriceSnapshot:
    price_date: date
    close_price: float
    previous_close: float
    price_change_percent: float | None
    currency: str | None


def _sanitize_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Z0-9.-]+", "", symbol.upper())


def _normalize_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


def _normalize_company_name(value: str) -> str:
    normalized_value = f" {_normalize_text(value)} "
    for suffix in (" LIMITED ", " LTD ", " LTD. ", " LIMITED. "):
        normalized_value = normalized_value.replace(suffix, " ")
    return " ".join(normalized_value.split())


def build_yahoo_symbol(symbol: str, exchange: str) -> str:
    sanitized_symbol = _sanitize_symbol(symbol)
    if sanitized_symbol.endswith(".NS") or sanitized_symbol.endswith(".BO"):
        return sanitized_symbol

    exchange_suffix = {
        "NSE": ".NS",
        "BSE": ".BO",
    }.get(exchange.upper())
    if exchange_suffix is None:
        raise MarketPriceError(f"Unsupported exchange: {exchange}")

    return f"{sanitized_symbol}{exchange_suffix}"


def _candidate_penalty(symbol: str) -> int:
    upper_symbol = symbol.upper()
    penalty = 0
    for marker in ("DVR", "-BL", "-BZ", "PREF", "PP"):
        if marker in upper_symbol:
            penalty -= 25
    return penalty


def _collect_yahoo_search_results(query: str):
    try:
        return yf.Search(
            query=query,
            max_results=8,
            news_count=0,
            lists_count=0,
            recommended=8,
            timeout=20,
            raise_errors=False,
        )
    except Exception:  # pragma: no cover - depends on network/library behavior
        return None


def _search_queries(query: str) -> list[str]:
    candidates = [query]
    simplified_query = _normalize_company_name(query)
    if simplified_query and simplified_query not in candidates:
        candidates.append(simplified_query)
    return candidates


def _search_yahoo_symbols(query: str, exchange: str) -> list[str]:
    preferred_suffix = {
        "NSE": ".NS",
        "BSE": ".BO",
    }.get(exchange.upper())
    if preferred_suffix is None:
        return []

    scored_symbols: list[tuple[int, str]] = []
    for search_query in _search_queries(query):
        search = _collect_yahoo_search_results(search_query)
        if search is None:
            continue

        normalized_query = _normalize_company_name(search_query)
        for quote in getattr(search, "quotes", []) or []:
            candidate_symbol = str(quote.get("symbol") or "").upper().strip()
            if not candidate_symbol:
                continue
            # Only consider Indian exchange symbols — skip NYSE ADRs, MX, SG, etc.
            if not (candidate_symbol.endswith(".NS") or candidate_symbol.endswith(".BO")):
                continue

            candidate_name = _normalize_company_name(
                str(
                    quote.get("shortname")
                    or quote.get("longname")
                    or quote.get("displayName")
                    or quote.get("prevName")
                    or ""
                )
            )
            previous_name = _normalize_company_name(str(quote.get("prevName") or ""))
            quote_type = str(quote.get("quoteType") or "").upper()
            score = 0
            if candidate_symbol.endswith(preferred_suffix):
                score += 50
            if quote_type == "EQUITY":
                score += 20
            if normalized_query and normalized_query == candidate_name:
                score += 25
            if normalized_query and normalized_query == previous_name:
                score += 25
            if normalized_query and normalized_query in candidate_name:
                score += 15
            if normalized_query and normalized_query in previous_name:
                score += 15
            score += _candidate_penalty(candidate_symbol)
            scored_symbols.append((score, candidate_symbol))

    unique_symbols: list[str] = []
    for _, candidate_symbol in sorted(scored_symbols, key=lambda item: item[0], reverse=True):
        if candidate_symbol not in unique_symbols:
            unique_symbols.append(candidate_symbol)
    return unique_symbols


def _build_candidate_symbols(symbol: str, exchange: str, search_query: str | None) -> list[str]:
    primary_candidate = build_yahoo_symbol(symbol, exchange)
    candidates = [primary_candidate]

    if search_query:
        candidates.extend(_search_yahoo_symbols(search_query, exchange))

    deduped_candidates: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped_candidates:
            deduped_candidates.append(candidate)
    return deduped_candidates


def _fetch_history(yahoo_symbol: str):
    try:
        return yf.Ticker(yahoo_symbol).history(
            period="5d",
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
    except Exception as exc:  # pragma: no cover - depends on network/library behavior
        raise MarketPriceError(f"Failed to fetch price data for {yahoo_symbol}") from exc


def _build_snapshot_from_history(history, yahoo_symbol: str) -> PriceSnapshot:
    if history is None or history.empty:
        raise MarketPriceError(f"No price data returned for {yahoo_symbol}")

    history = history.dropna(subset=["Close"])
    if len(history.index) < 2:
        raise MarketPriceError(f"Not enough daily history returned for {yahoo_symbol}")

    latest_rows = history.tail(2)
    latest_close = float(latest_rows["Close"].iloc[-1])
    previous_close = float(latest_rows["Close"].iloc[-2])
    price_change_percent = None
    if previous_close:
        price_change_percent = round(((latest_close - previous_close) / previous_close) * 100, 4)

    return PriceSnapshot(
        price_date=latest_rows.index[-1].date(),
        close_price=round(latest_close, 4),
        previous_close=round(previous_close, 4),
        price_change_percent=price_change_percent,
        currency="INR",
    )


def fetch_yfinance_news(
    yahoo_symbol: str,
    *,
    limit: int = 5,
    target_date: date | None = None,
) -> list[dict]:
    """Fetch news articles from Yahoo Finance for the given ticker symbol.

    Returns articles normalised to the same shape used by google_news_service:
    {title, url, source, published_at (ISO-8601 str), snippet}.
    """
    try:
        raw_news = yf.Ticker(yahoo_symbol).news or []
    except Exception:
        return []

    articles: list[dict] = []
    cutoff = (target_date - timedelta(days=3)) if target_date else None

    for item in raw_news:
        if len(articles) >= limit:
            break
        try:
            title = str(item.get("title") or "").strip()
            link = str(item.get("link") or item.get("url") or "").strip()
            if not title or not link:
                continue

            pub_ts = item.get("providerPublishTime")
            published_at: str | None = None
            if pub_ts:
                pub_dt = datetime.fromtimestamp(int(pub_ts), tz=timezone.utc)
                published_at = pub_dt.isoformat()
                if cutoff and pub_dt.date() < cutoff:
                    continue  # article is too old for the target window

            articles.append(
                {
                    "title": title,
                    "url": link,
                    "source": str(item.get("publisher") or "") or None,
                    "published_at": published_at,
                    "snippet": None,
                }
            )
        except Exception:
            continue

    return articles


def fetch_price_snapshot(symbol: str, exchange: str, *, search_query: str | None = None) -> PriceSnapshot:
    errors: list[str] = []
    for yahoo_symbol in _build_candidate_symbols(symbol, exchange, search_query):
        try:
            history = _fetch_history(yahoo_symbol)
            return _build_snapshot_from_history(history, yahoo_symbol)
        except MarketPriceError as exc:
            errors.append(str(exc))
            continue

    raise MarketPriceError("; ".join(errors) or f"Unable to fetch price data for {symbol}")
