"""Structured error handling: every error path — an app-raised business
error, a Pydantic validation failure, a routine HTTP error (404, ...), or
an unhandled bug — renders the same JSON shape:

    {"error": {"code": "...", "message": "...", "details": [...optional]}}

so a caller (the Studio dashboard, later any other client) never has to
branch on which failure mode produced a response. Unhandled exceptions
are logged with a traceback server-side but never leak their message to
the client — Section 13's data-leakage concern applies to error responses
too, not just deliberate data access.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base for errors this app raises deliberately, as opposed to bugs."""

    def __init__(
        self, message: str, *, code: str = "app_error", status_code: int = status.HTTP_400_BAD_REQUEST
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def _error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", "Request validation failed.", exc.errors()
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception while processing %s %s", request.method, request.url.path)
        return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "An unexpected error occurred.")
