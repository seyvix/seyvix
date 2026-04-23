from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.schemas import ErrorDetail, ErrorResponse


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return build_error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "type": error["type"],
                "location": list(error["loc"]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return build_error_response(
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details=details,
        )
