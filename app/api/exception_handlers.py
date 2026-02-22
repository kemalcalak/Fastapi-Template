import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi.errors import RateLimitExceeded

from app.core.messages.error_message import ErrorMessages

logger = logging.getLogger(__name__)


async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors with success: false and details."""
    errors = []
    for error in exc.errors():
        loc = error.get("loc", [])
        field = loc[-1] if loc else "unknown"
        # We return the raw error message or key from Pydantic/Validator
        errors.append({"field": str(field), "error_key": error.get("msg")})

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": ErrorMessages.VALIDATION_ERROR,
            "details": errors,
        },
    )


async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions (404, 401, etc.) with success: false."""
    detail = str(exc.detail)

    status_error_map = {
        400: ErrorMessages.VALIDATION_ERROR,
        401: ErrorMessages.INVALID_TOKEN,
        403: ErrorMessages.INSUFFICIENT_PERMISSIONS,
        404: ErrorMessages.RESOURCE_NOT_FOUND,
        409: ErrorMessages.RESOURCE_CONFLICT,
    }

    # If the detail looks like an i18n key (contains . or is all caps), use it,
    # otherwise fallback to status code based key.
    error_key = (
        detail
        if ("." in detail or detail.isupper())
        else status_error_map.get(exc.status_code, ErrorMessages.INTERNAL_SERVER_ERROR)
    )

    return JSONResponse(
        status_code=exc.status_code, content={"success": False, "error": error_key}
    )


async def general_exception_handler(_request: Request, exc: Exception):
    """Handle unexpected server errors, hide details, and return success: false."""
    logger.error(f"Unhandled Exception: {str(exc)}", exc_info=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "error": ErrorMessages.INTERNAL_SERVER_ERROR},
    )


async def rate_limit_exception_handler(_request: Request, exc: RateLimitExceeded):
    """Handle Rate Limiting (429) errors."""
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"success": False, "error": ErrorMessages.RATE_LIMIT_EXCEEDED, "detail": str(exc)},
    )
