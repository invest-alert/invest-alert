from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.responses import error_response_content


def _status_code_name(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).name
    except ValueError:
        return f"HTTP_{status_code}"


def _http_exception_message_and_details(detail: Any) -> tuple[str, Any]:
    if isinstance(detail, str):
        return detail, None
    if isinstance(detail, dict):
        message = detail.get("message", "Request failed")
        details = detail.get("details", detail)
        return message, details
    if isinstance(detail, list):
        return "Request validation failed", detail
    return "Request failed", detail


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_response_content(
                message="Validation error",
                code="VALIDATION_ERROR",
                details=exc.errors(),
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message, details = _http_exception_message_and_details(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response_content(
                message=message,
                code=_status_code_name(exc.status_code),
                details=details,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        message, details = _http_exception_message_and_details(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response_content(
                message=message,
                code=_status_code_name(exc.status_code),
                details=details,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=error_response_content(
                message="Internal server error",
                code="INTERNAL_SERVER_ERROR",
            ),
        )
