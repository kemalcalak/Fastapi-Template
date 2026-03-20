import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

from app.api.exception_handlers import (
    general_exception_handler,
    http_exception_handler,
    rate_limit_exception_handler,
    validation_exception_handler,
)
from app.api.main import api_router
from app.core.config import settings
from app.core.messages.error_message import ErrorMessages
from app.core.rate_limit import limiter


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

# Exception Handlers
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
app.state.limiter = limiter


@app.middleware("http")
async def origin_check_middleware(request: Request, call_next):
    """
    Strict origin check. Returns 404 for unauthorized origins.
    Allows same-origin requests (from the API's own origin).
    Hides error details and ensures always 404 for these cases.
    """
    origin = request.headers.get("origin")
    if origin:
        origin = origin.rstrip("/")

    # Allow same-origin requests
    if origin:
        # Reconstruct the request's own origin from scheme and host header
        scheme = request.url.scheme
        host = request.headers.get("host", "").rstrip("/")
        request_origin = f"{scheme}://{host}".rstrip("/")

        # Allow if origins match (same-origin request)
        if origin == request_origin:
            return await call_next(request)

    allowed_origins = settings.all_cors_origins

    if origin and allowed_origins and "*" not in allowed_origins:
        if origin not in allowed_origins:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": ErrorMessages.RESOURCE_NOT_FOUND},
            )
    return await call_next(request)


# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
