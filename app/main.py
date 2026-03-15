from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router, root_router
from app.core.config import settings
from app.core.error_handlers import register_exception_handlers
from app.services.context_scheduler import start_context_scheduler, stop_context_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler = start_context_scheduler()
    try:
        yield
    finally:
        stop_context_scheduler(scheduler)


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
register_exception_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.cors_allow_methods_list,
    allow_headers=settings.cors_allow_headers_list,
)
app.include_router(root_router)
app.include_router(api_router)
