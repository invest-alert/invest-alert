from fastapi import FastAPI

from app.api.router import api_router, root_router
from app.core.config import settings
from app.core.error_handlers import register_exception_handlers

app = FastAPI(title=settings.APP_NAME)
register_exception_handlers(app)
app.include_router(root_router)
app.include_router(api_router)
