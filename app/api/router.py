from fastapi import APIRouter

from app.api.v1.api import api_v1_router
from app.api.v1.endpoints.health import router as health_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(api_v1_router)

root_router = APIRouter()
root_router.include_router(health_router)
