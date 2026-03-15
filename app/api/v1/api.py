from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.daily_context import router as daily_context_router
from app.api.v1.endpoints.watchlist import router as watchlist_router

api_v1_router = APIRouter()
api_v1_router.include_router(auth_router)
api_v1_router.include_router(daily_context_router)
api_v1_router.include_router(watchlist_router)
