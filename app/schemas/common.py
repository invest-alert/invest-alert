from typing import Any

from pydantic import BaseModel


class ErrorInfo(BaseModel):
    code: str
    details: Any | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
    error: ErrorInfo | None = None
