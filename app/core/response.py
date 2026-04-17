from typing import Any, Generic, TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str


class APIResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    message: str | None = None
    error: ErrorDetail | None = None


class ErrorResponse(BaseModel):
    """Base shape for the error envelope used in Swagger docs."""

    success: bool = False
    error: ErrorDetail


class BadRequestResponse(ErrorResponse):
    error: ErrorDetail = Field(
        default=ErrorDetail(code="BAD_REQUEST", message="The request is invalid")
    )


class UnauthorizedResponse(ErrorResponse):
    error: ErrorDetail = Field(
        default=ErrorDetail(code="UNAUTHORIZED", message="Authentication is required")
    )


class ForbiddenResponse(ErrorResponse):
    error: ErrorDetail = Field(
        default=ErrorDetail(code="FORBIDDEN", message="Access is forbidden")
    )


class NotFoundResponse(ErrorResponse):
    error: ErrorDetail = Field(
        default=ErrorDetail(
            code="NOT_FOUND", message="The requested resource was not found"
        )
    )


class ConflictResponse(ErrorResponse):
    error: ErrorDetail = Field(
        default=ErrorDetail(
            code="CONFLICT", message="The request conflicts with the current state"
        )
    )


class ValidationErrorResponse(ErrorResponse):
    error: ErrorDetail = Field(
        default=ErrorDetail(
            code="VALIDATION_ERROR", message="The request payload failed validation"
        )
    )


class TooManyRequestsResponse(ErrorResponse):
    error: ErrorDetail = Field(
        default=ErrorDetail(code="TOO_MANY_REQUESTS", message="Rate limit exceeded")
    )


class InternalServerErrorResponse(ErrorResponse):
    error: ErrorDetail = Field(
        default=ErrorDetail(
            code="INTERNAL_SERVER_ERROR", message="An unexpected error occurred"
        )
    )


def success_response(
    data: Any = None,
    message: str | None = None,
    status_code: int = 200,
) -> JSONResponse:
    body = APIResponse(success=True, data=data, message=message)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True, mode="json"),
    )


def error_response(
    code: str,
    message: str,
    status_code: int = 400,
) -> JSONResponse:
    body = APIResponse(
        success=False,
        error=ErrorDetail(code=code, message=message),
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True, mode="json"),
    )
