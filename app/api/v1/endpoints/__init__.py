from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.watchlist import router as watchlist_router

__all__ = ["auth_router", "health_router", "watchlist_router"]
