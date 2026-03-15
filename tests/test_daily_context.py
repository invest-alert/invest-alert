from datetime import date

import pandas as pd

from app.db.session import SessionLocal
from app.services import article_summary_service
from app.services import market_price_service
from app.services.market_price_service import PriceSnapshot
from app.services.marketaux_service import MarketauxError, ResolvedEquity, filter_articles_for_company


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _register_user(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123"},
    )
    token = response.json()["data"]["access_token"]
    return _auth_headers(token)


def test_filter_articles_for_company_keeps_exact_matches_only():
    articles = [
        {
            "title": "Tata Motors launches a new EV platform",
            "description": "Tata Motors plans to expand its EV line-up in India.",
            "url": "https://example.com/1",
        },
        {
            "title": "Tata Steel gains after quarterly update",
            "description": "Investors react to Tata Steel results.",
            "url": "https://example.com/2",
        },
        {
            "title": "Auto sector outlook improves",
            "description": "Brokerages are upbeat on passenger vehicle demand.",
            "url": "https://example.com/3",
        },
    ]

    filtered = filter_articles_for_company(articles, "TATA MOTORS", article_limit=3)

    assert len(filtered) == 1
    assert filtered[0]["title"] == "Tata Motors launches a new EV platform"


def test_filter_articles_for_company_drops_body_only_mentions():
    articles = [
        {
            "title": "HDFC Bank, Axis Bank and PNB collected highest minimum balance charges",
            "description": "Parliamentary data showed large minimum-balance penalty collections.",
            "snippet": "Banks collected significant penalties from customers for low balances.",
            "text": "IDBI Bank Limited appeared lower in the broader ranking table.",
            "entities": [{"name": "HDFC Bank Limited"}],
            "url": "https://example.com/idbi-weak-match",
        }
    ]

    filtered = filter_articles_for_company(articles, "IDBI BANK", article_limit=3)

    assert filtered == []


def test_filter_articles_for_company_accepts_legal_name_variant_in_entities():
    articles = [
        {
            "title": "EV discounts hit 5 lakh as fuel jitters, tax perks and PLI targets drive March end sales",
            "description": "Automakers offer discounts exceeding 5 lakh on EVs, driven by fuel concerns and tax incentives.",
            "snippet": "Automakers are rolling out some of the steepest discounts yet on electric vehicles.",
            "entities": [{"name": "TATA MOTORS LTD."}],
            "url": "https://example.com/tata-variant",
        }
    ]

    filtered = filter_articles_for_company(articles, "TATA MOTORS LTD.", article_limit=3)

    assert len(filtered) == 1
    assert filtered[0]["title"].startswith("EV discounts hit")


def test_extract_article_content_strips_et_boilerplate():
    html = """
    <html>
      <head>
        <meta name="description" content="Minimum balance charges: Banks collected significant penalties from customers for low account balances." />
      </head>
      <body>
        <script type="application/ld+json">
          [{
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "HDFC Bank, Axis Bank and PNB collected highest minimum balance charges",
            "description": "Minimum balance charges: Banks collected significant penalties from customers for low account balances.",
            "articleBody": "HDFC Bank, Axis Bank and Punjab National Bank (PNB) received the highest penalties in FY 22-23, FY 23-24 and FY 24-25 from their customers for not maintaining the required minimum balance in savings and current accounts, according to data shared by the Finance Ministry in the Lok Sabha. In a reply to an unstarred question in Lok Sabha on March 9, 2026, the data was provided by the Ministry of Finance in response to a question regarding charges levied for non-maintenance of Minimum Average Balance (MAB) in bank accounts. Read more news on HDFC Bank penalties Catch all the Personal Finance News. Lessons from the Grandmasters"
          }]
        </script>
      </body>
    </html>
    """

    content = article_summary_service._extract_article_content(
        html,
        url="https://economictimes.indiatimes.com/wealth/invest/example/articleshow/123.cms",
    )
    summary = article_summary_service.summarize_text(
        content.summary_input,
        headline_title="HDFC Bank, Axis Bank and PNB collected highest minimum balance charges",
        article_description=content.description,
    )

    assert content.summary_source == "article_jsonld"
    assert "Read more news on" not in content.article_text
    assert "Lessons from the Grandmasters" not in content.article_text
    assert "HDFC Bank, Axis Bank and Punjab National Bank" in summary


def test_extract_article_content_prefers_businessline_article_body():
    html = """
    <html>
      <head>
        <meta name="description" content="Automakers offer discounts exceeding ₹5 lakh on EVs, driven by fuel concerns and tax incentives." />
      </head>
      <body>
        <main>
          <p>This is a generic page shell that should not win extraction.</p>
        </main>
        <div itemprop="articleBody">
          <p>Automakers are rolling out some of the steepest discounts yet on electric vehicles as fuel uncertainty and fiscal incentives push manufacturers to accelerate sales before year-end.</p>
          <p>Tata Motors is offering discounts of up to ₹3.8 lakh across select electric models as part of its Mega March Carnival, including the Curvv EV, Nexon.ev and Tiago.ev.</p>
          <p>Read more news on Tata Motors</p>
        </div>
      </body>
    </html>
    """

    content = article_summary_service._extract_article_content(
        html,
        url="https://www.thehindubusinessline.com/companies/example/article123.ece",
    )

    assert content.summary_source == "article_dom:[itemprop='articleBody']"
    assert "generic page shell" not in content.article_text.lower()
    assert "Read more news on" not in content.article_text
    assert "Tata Motors is offering discounts" in content.summary_input


def test_harvest_daily_context_for_user(client, monkeypatch):
    headers = _register_user(client, "harvest@example.com")
    watchlist_response = client.post(
        "/api/v1/watchlist",
        json={"symbol": "Tata Motors", "exchange": "NSE"},
        headers=headers,
    )
    assert watchlist_response.status_code == 201

    def fake_resolve_equity(query: str, exchange: str) -> ResolvedEquity:
        return ResolvedEquity(symbol="TATAMOTORS", company_name="TATA MOTORS")

    def fake_fetch_price_snapshot(
        symbol: str,
        exchange: str,
        *,
        search_query: str | None = None,
    ) -> PriceSnapshot:
        return PriceSnapshot(
            price_date=date(2026, 3, 13),
            close_price=672.50,
            previous_close=660.00,
            price_change_percent=1.8939,
            currency="INR",
        )

    def fake_fetch_company_news(
        company_name: str,
        *,
        market_symbol: str | None = None,
        target_date: date | None = None,
        article_limit: int | None = None,
    ) -> list[dict]:
        return [
            {
                "title": "Tata Motors secures a large EV fleet order",
                "url": "https://example.com/tata-1",
                "source": "Mock Source",
                "published_at": "2026-03-13T10:15:00Z",
                "snippet": "Tata Motors won a large EV fleet order from a major operator.",
            },
            {
                "title": "Tata Motors expands production capacity",
                "url": "https://example.com/tata-2",
                "source": "Mock Source",
                "published_at": "2026-03-13T11:45:00Z",
                "snippet": "The company is expanding production capacity to support growth.",
            },
        ]

    def fake_summarize_headline(db, headline: dict) -> dict:
        return {
            **headline,
            "summary": f"Summary for {headline['title']}",
            "summary_status": "completed",
            "summary_error": None,
            "summary_source": "test_stub",
            "summary_generated_at": "2026-03-13T12:00:00Z",
            "content_excerpt": "Short article excerpt",
        }

    monkeypatch.setattr("app.services.daily_context_service.resolve_equity", fake_resolve_equity)
    monkeypatch.setattr(
        "app.services.daily_context_service.fetch_price_snapshot",
        fake_fetch_price_snapshot,
    )
    monkeypatch.setattr("app.services.daily_context_service.fetch_company_news", fake_fetch_company_news)
    monkeypatch.setattr(
        "app.services.article_summary_service.summarize_headline",
        fake_summarize_headline,
    )

    harvest_response = client.post("/api/v1/daily-context/harvest?date=2026-03-13", headers=headers)
    assert harvest_response.status_code == 201
    harvest_payload = harvest_response.json()["data"]
    assert harvest_payload["processed_count"] == 1
    assert harvest_payload["saved_count"] == 1
    assert harvest_payload["contexts"][0]["resolved_symbol"] == "TATAMOTORS"
    assert harvest_payload["contexts"][0]["article_count"] == 2
    assert harvest_payload["contexts"][0]["summary_status"] == "queued"
    assert harvest_payload["contexts"][0]["top_headlines"][0]["summary_status"] == "pending"

    task_id = harvest_payload["contexts"][0]["summary_job_id"]
    assert task_id is not None

    db = SessionLocal()
    try:
        processed_jobs = article_summary_service.process_pending_summary_jobs(db, limit=5)
        assert processed_jobs == 1
    finally:
        db.close()

    task_response = client.get(f"/api/v1/daily-context/tasks/{task_id}", headers=headers)
    assert task_response.status_code == 200
    assert task_response.json()["data"]["successful"] is True
    assert task_response.json()["data"]["status"] == "completed"

    context_list_response = client.get("/api/v1/daily-context?date=2026-03-13", headers=headers)
    assert context_list_response.status_code == 200
    contexts = context_list_response.json()["data"]
    assert len(contexts) == 1
    assert contexts[0]["company_name"] == "TATA MOTORS"
    assert contexts[0]["close_price"] == 672.5
    assert contexts[0]["summary_status"] == "completed"
    assert contexts[0]["top_headlines"][0]["summary"] == (
        "Summary for Tata Motors secures a large EV fleet order"
    )
    assert contexts[0]["top_headlines"][1]["summary_source"] == "test_stub"


def test_fetch_price_snapshot_falls_back_to_yahoo_search(monkeypatch):
    class FakeSearch:
        def __init__(self, *args, **kwargs):
            self.quotes = [
                {
                    "symbol": "TATAMTRDVR-BL.NS",
                    "shortname": "Tata Motors DVR",
                    "quoteType": "EQUITY",
                },
                {
                    "symbol": "TATAMOTORS.NS",
                    "shortname": "Tata Motors Ltd",
                    "quoteType": "EQUITY",
                },
            ]

    class FakeTicker:
        def __init__(self, symbol: str):
            self.symbol = symbol

        def history(self, **kwargs):
            if self.symbol == "TATAMTRDVR-BL.NS":
                return pd.DataFrame()
            return pd.DataFrame(
                {"Close": [660.0, 672.5]},
                index=pd.to_datetime(["2026-03-12", "2026-03-13"]),
            )

    monkeypatch.setattr(market_price_service.yf, "Search", FakeSearch)
    monkeypatch.setattr(market_price_service.yf, "Ticker", FakeTicker)

    snapshot = market_price_service.fetch_price_snapshot(
        "TATAMTRDVR-BL.NS",
        "NSE",
        search_query="TATA MOTORS LTD.",
    )

    assert snapshot.close_price == 672.5
    assert snapshot.previous_close == 660.0
    assert snapshot.price_change_percent == 1.8939


def test_requeue_daily_context_summary_job(client, monkeypatch):
    headers = _register_user(client, "summary-requeue@example.com")
    add_response = client.post(
        "/api/v1/watchlist",
        json={"symbol": "Tata Motors", "exchange": "NSE"},
        headers=headers,
    )
    assert add_response.status_code == 201

    def fake_resolve_equity(query: str, exchange: str) -> ResolvedEquity:
        return ResolvedEquity(symbol="TATAMOTORS", company_name="TATA MOTORS")

    def fake_fetch_price_snapshot(
        symbol: str,
        exchange: str,
        *,
        search_query: str | None = None,
    ) -> PriceSnapshot:
        return PriceSnapshot(
            price_date=date(2026, 3, 13),
            close_price=100.0,
            previous_close=99.0,
            price_change_percent=1.0101,
            currency="INR",
        )

    def fake_fetch_company_news(
        company_name: str,
        *,
        market_symbol: str | None = None,
        target_date: date | None = None,
        article_limit: int | None = None,
    ) -> list[dict]:
        return [
            {
                "title": "Tata Motors wins another order",
                "url": "https://example.com/tata-3",
                "source": "Mock Source",
                "published_at": "2026-03-13T12:30:00Z",
                "snippet": "Tata Motors received another order.",
            }
        ]

    def fake_summarize_headline(db, headline: dict) -> dict:
        return {
            **headline,
            "summary": "Retry summary output",
            "summary_status": "completed",
            "summary_error": None,
            "summary_source": "test_stub",
            "summary_generated_at": "2026-03-13T12:35:00Z",
            "content_excerpt": "Retry excerpt",
        }

    monkeypatch.setattr("app.services.daily_context_service.resolve_equity", fake_resolve_equity)
    monkeypatch.setattr("app.services.daily_context_service.fetch_price_snapshot", fake_fetch_price_snapshot)
    monkeypatch.setattr("app.services.daily_context_service.fetch_company_news", fake_fetch_company_news)
    monkeypatch.setattr("app.services.article_summary_service.summarize_headline", fake_summarize_headline)

    harvest_response = client.post("/api/v1/daily-context/harvest?date=2026-03-13", headers=headers)
    context_id = harvest_response.json()["data"]["contexts"][0]["id"]

    requeue_response = client.post(f"/api/v1/daily-context/{context_id}/summaries", headers=headers)
    assert requeue_response.status_code == 202
    assert requeue_response.json()["data"]["summary_status"] == "queued"

    db = SessionLocal()
    try:
        processed_jobs = article_summary_service.process_pending_summary_jobs(db, limit=5)
        assert processed_jobs == 1
    finally:
        db.close()

    refreshed_context_response = client.get("/api/v1/daily-context?date=2026-03-13", headers=headers)
    refreshed_context = refreshed_context_response.json()["data"][0]
    assert refreshed_context["summary_status"] == "completed"
    assert refreshed_context["top_headlines"][0]["summary"] == "Retry summary output"


def test_harvest_daily_context_uses_google_news_fallback(client, monkeypatch):
    headers = _register_user(client, "google-fallback@example.com")
    add_response = client.post(
        "/api/v1/watchlist",
        json={"symbol": "Infosys", "exchange": "NSE"},
        headers=headers,
    )
    assert add_response.status_code == 201

    def fake_resolve_equity(query: str, exchange: str) -> ResolvedEquity:
        return ResolvedEquity(symbol="INFY.NS", company_name="Infosys Limited")

    def fake_fetch_price_snapshot(
        symbol: str,
        exchange: str,
        *,
        search_query: str | None = None,
    ) -> PriceSnapshot:
        return PriceSnapshot(
            price_date=date(2026, 3, 13),
            close_price=1500.0,
            previous_close=1490.0,
            price_change_percent=0.6711,
            currency="INR",
        )

    def fake_fetch_company_news(
        company_name: str,
        *,
        market_symbol: str | None = None,
        target_date: date | None = None,
        article_limit: int | None = None,
    ) -> list[dict]:
        return []

    def fake_fetch_google_news(
        company_name: str,
        *,
        target_date: date | None = None,
        article_limit: int | None = None,
    ) -> list[dict]:
        return [
            {
                "title": "Infosys signs new enterprise AI deal",
                "url": "https://example.com/infosys-1",
                "source": "Mock Source",
                "published_at": "2026-03-13T12:00:00Z",
                "snippet": "Infosys announced a new enterprise AI partnership.",
            }
        ]

    monkeypatch.setattr("app.services.daily_context_service.resolve_equity", fake_resolve_equity)
    monkeypatch.setattr("app.services.daily_context_service.fetch_price_snapshot", fake_fetch_price_snapshot)
    monkeypatch.setattr("app.services.daily_context_service.fetch_company_news", fake_fetch_company_news)
    monkeypatch.setattr("app.services.daily_context_service.fetch_google_news", fake_fetch_google_news)

    harvest_response = client.post("/api/v1/daily-context/harvest?date=2026-03-13", headers=headers)
    assert harvest_response.status_code == 201
    context = harvest_response.json()["data"]["contexts"][0]
    assert context["article_count"] == 1
    assert context["top_headlines"][0]["title"] == "Infosys signs new enterprise AI deal"


def test_harvest_daily_context_uses_google_news_when_marketaux_errors(client, monkeypatch):
    headers = _register_user(client, "google-fallback-error@example.com")
    add_response = client.post(
        "/api/v1/watchlist",
        json={"symbol": "Infosys", "exchange": "NSE"},
        headers=headers,
    )
    assert add_response.status_code == 201

    def fake_resolve_equity(query: str, exchange: str) -> ResolvedEquity:
        return ResolvedEquity(symbol="INFY.NS", company_name="Infosys Limited")

    def fake_fetch_price_snapshot(
        symbol: str,
        exchange: str,
        *,
        search_query: str | None = None,
    ) -> PriceSnapshot:
        return PriceSnapshot(
            price_date=date(2026, 3, 13),
            close_price=1500.0,
            previous_close=1490.0,
            price_change_percent=0.6711,
            currency="INR",
        )

    def fake_fetch_company_news(
        company_name: str,
        *,
        market_symbol: str | None = None,
        target_date: date | None = None,
        article_limit: int | None = None,
    ) -> list[dict]:
        raise MarketauxError("usage limit reached")

    def fake_fetch_google_news(
        company_name: str,
        *,
        target_date: date | None = None,
        article_limit: int | None = None,
    ) -> list[dict]:
        return [
            {
                "title": "Infosys expands cloud modernization partnership",
                "url": "https://example.com/infosys-2",
                "source": "Mock Source",
                "published_at": "2026-03-13T12:00:00Z",
                "snippet": "Infosys announced a broader cloud modernization engagement.",
            }
        ]

    monkeypatch.setattr("app.services.daily_context_service.resolve_equity", fake_resolve_equity)
    monkeypatch.setattr("app.services.daily_context_service.fetch_price_snapshot", fake_fetch_price_snapshot)
    monkeypatch.setattr("app.services.daily_context_service.fetch_company_news", fake_fetch_company_news)
    monkeypatch.setattr("app.services.daily_context_service.fetch_google_news", fake_fetch_google_news)

    harvest_response = client.post("/api/v1/daily-context/harvest?date=2026-03-13", headers=headers)
    assert harvest_response.status_code == 201
    context = harvest_response.json()["data"]["contexts"][0]
    assert context["article_count"] == 1
    assert context["top_headlines"][0]["title"] == "Infosys expands cloud modernization partnership"
