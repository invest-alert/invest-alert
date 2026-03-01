# Invest Alert (Milestone 1 Backend)

FastAPI + PostgreSQL backend for:
- JWT auth (`register`, `login`, `refresh`, `logout`, `me`)
- Watchlist management (`GET`, `POST`, `DELETE`) with a max limit of 15 stocks/user
- Global success/error response envelope for frontend consistency

## Project structure

```text
my_fastapi_project/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── auth.py
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
│   │   ├── users.py
│   │   ├── refresh_tokens.py
│   │   └── watchlist.py
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── __init__.py
│   ├── models/
│   │   ├── user.py
│   │   ├── refresh_token.py
│   │   └── watchlist_stock.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── watchlist.py
│   │   └── common.py
│   ├── services/
│   │   ├── auth_service.py
│   │   └── watchlist_service.py
│   └── main.py
├── tests/
│   ├── conftest.py
│   ├── test_auth_and_watchlist.py
│   └── test_users.py
├── requirements.txt
├── Dockerfile
├── .env
└── README.md
```

## 1. Local setup

```powershell
cd "F:\Invest Alert\invest-alert"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `.env` with your local PostgreSQL credentials.
If your frontend runs on a different origin, set `CORS_ALLOW_ORIGINS` in `.env`
(comma-separated list, for example `http://localhost:3000,http://localhost:5173`).

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

## 6. Tests

```powershell
pytest -q
```
