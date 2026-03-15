# Invest Alert Backend (Milestone 1 + 2.5)

FastAPI + PostgreSQL backend for:
- JWT auth (`register`, `login`, `refresh`, `logout`, `me`)
- Watchlist management (`GET`, `POST`, `DELETE`) with a max limit of 15 stocks/user
- Daily context harvesting for stock price change + top 3 filtered news headlines
- Asynchronous article extraction + summary generation for harvested headlines
- Global success/error response envelope for frontend consistency

## Project structure

```text
my_fastapi_project/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── auth.py
│   │   │   │   ├── daily_context.py
│   │   │   │   ├── watchlist.py
│   │   │   │   └── health.py
│   │   │   └── api.py
│   │   ├── deps.py
│   │   └── router.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── responses.py
│   │   └── error_handlers.py
│   ├── crud/
│   │   ├── article_summary_cache.py
│   │   ├── daily_contexts.py
│   │   ├── users.py
│   │   ├── refresh_tokens.py
│   │   ├── summary_jobs.py
│   │   └── watchlist.py
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── __init__.py
│   ├── models/
│   │   ├── article_summary_cache.py
│   │   ├── daily_context.py
│   │   ├── summary_job.py
│   │   ├── user.py
│   │   ├── refresh_token.py
│   │   └── watchlist_stock.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── daily_context.py
│   │   ├── watchlist.py
│   │   └── common.py
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── article_summary_service.py
│   │   ├── context_scheduler.py
│   │   ├── daily_context_service.py
│   │   ├── google_news_service.py
│   │   ├── market_price_service.py
│   │   ├── marketaux_service.py
│   │   └── watchlist_service.py
│   └── main.py
├── tests/
│   ├── conftest.py
│   ├── test_auth_and_watchlist.py
│   ├── test_daily_context.py
│   └── test_users.py
├── requirements.txt
├── Dockerfile
├── .env
└── README.md
```

## 1. Local setup

```powershell
cd "Invest Alert\invest-alert"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `.env` with your local PostgreSQL credentials.
If your frontend runs on a different origin, set `CORS_ALLOW_ORIGINS` in `.env`
(comma-separated list, for example `http://localhost:3000,http://localhost:5173`).
For Milestone 2, set `MARKETAUX_API_KEY` for primary news harvesting. If Marketaux returns no useful articles, the backend falls back to Google News RSS automatically.

For asynchronous article summaries, the app now uses:
- PostgreSQL as the job queue and summary cache store
- the built-in APScheduler worker loop inside the API process

No Redis or Celery setup is required for the MVP.

## 2. Run migrations

```powershell
alembic upgrade head
```

## 3. Start API server

```powershell
uvicorn app.main:app --reload
```

Open:
- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## 4. Global response contract

Successful response:

```json
{
  "success": true,
  "message": "Login successful",
  "data": {
    "access_token": "...",
    "refresh_token": "...",
    "token_type": "bearer"
  },
  "error": null
}
```

Error response:

```json
{
  "success": false,
  "message": "Validation error",
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "details": []
  }
}
```

## 5. API endpoints

Auth:
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/token` (OAuth form login for Swagger)
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Watchlist (Bearer access token required):
- `GET /api/v1/watchlist`
- `POST /api/v1/watchlist`
- `DELETE /api/v1/watchlist/{stock_id}`

`symbol` accepts ticker or company name (for example `TCS` or `Tata Motors`).

Daily Context (Bearer access token required):
- `GET /api/v1/daily-context`
- `POST /api/v1/daily-context/harvest`
- `POST /api/v1/daily-context/{context_id}/summaries`
- `GET /api/v1/daily-context/tasks/{task_id}`

Example manual harvest:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/daily-context/harvest?date=2026-03-13" `
  -Headers @{ Authorization = "Bearer <access_token>" }
```

The harvester:
- resolves company metadata into a reusable market symbol via Yahoo search
- fetches recent daily close and percent change via `yfinance`
- fetches finance news via `Marketaux`
- falls back to `Google News RSS` when Marketaux returns no useful articles
- drops any article that does not explicitly mention the company in the article metadata
- stores the final context in `daily_contexts`
- queues article extraction + summary generation for each saved daily context

Headline summaries:
- are generated asynchronously by a Postgres-backed worker loop
- fetch the article page from the headline URL
- extract the main article content
- generate a short summary and content excerpt
- store summary metadata back into `top_headlines`
- use a Postgres cache table to avoid re-summarizing the same URL repeatedly

Daily-context summary state:
- `not_available`
- `queued`
- `processing`
- `completed`
- `partial`
- `failed`
- `queue_failed`

Optional scheduler:
- `ENABLE_CONTEXT_SCHEDULER=true`
- `CONTEXT_HARVEST_HOUR=17`
- `CONTEXT_HARVEST_MINUTE=15`
- `CONTEXT_HARVEST_TIMEZONE=Asia/Kolkata`

Summary worker settings:
- `ENABLE_SUMMARY_WORKER=true`
- `SUMMARY_WORKER_INTERVAL_SECONDS=10`
- `SUMMARY_WORKER_BATCH_SIZE=3`

## 6. Tests

```powershell
pytest -q
```

## 7. Apache Bench load testing

Apache Bench (`ab`) is useful here for repeatable endpoint-level benchmarking. A few endpoints in this API are stateful, so they need different handling:

- Safe to stress with higher concurrency: `GET /health`, `POST /auth/login`, `POST /auth/token`, `GET /auth/me`, `GET /watchlist`, `GET /daily-context`
- Run carefully with low concurrency: `POST /daily-context/harvest`
- Smoke-style only with `ab`: `POST /auth/register`, `POST /auth/refresh`, `POST /auth/logout`, `POST /watchlist`, `DELETE /watchlist/{stock_id}`

Reason: `ab` replays the exact same request every time, so repeated `register`, `refresh`, `logout`, and `POST /watchlist` calls stop being representative after the first successful request.

Before running benchmarks:

1. Start the API locally.
2. Make sure `ab` is installed and available on `PATH`.
3. Keep `MARKETAUX_API_KEY` configured if you want the primary harvest path enabled.

Use the helper script:

```powershell
.\scripts\run_load_tests.ps1 `
  -BaseUrl "http://127.0.0.1:8000" `
  -Requests 200 `
  -Concurrency 20 `
  -HarvestRequests 2 `
  -HarvestConcurrency 1
```

What the script does:

- creates or logs into a dedicated benchmark user
- gets a bearer token for protected endpoints
- seeds `Tata Motors` into the watchlist if needed
- runs `ab` against the public, authenticated, harvest, and stateful endpoints
- stores each `ab` output in `artifacts/loadtest/<timestamp>/`

Useful options:

- `-SkipHarvest` to avoid external API traffic during a run
- `-SkipStateful` to benchmark only the repeatable endpoints
- `-DisableKeepAlive` to compare connection reuse vs no keep-alive
- `-Email` / `-Password` to reuse a specific benchmark user

Example: benchmark only the repeatable endpoints

```powershell
.\scripts\run_load_tests.ps1 `
  -Requests 500 `
  -Concurrency 50 `
  -SkipHarvest `
  -SkipStateful
```

Results are written as raw `ab` reports, so you will see:

- requests per second
- time per request
- transfer rate
- percentile latency breakdown

For Milestone 2 specifically, keep harvest load low. That endpoint calls external providers (`yfinance`, `Marketaux`, `Google News RSS`) and response times will vary based on network and provider throttling, not only your FastAPI server.
