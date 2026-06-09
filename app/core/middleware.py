"""HTTP middleware registration: strict origin check + CORS.

The origin check runs on every request and returns a generic 404 for
foreign origins — same shape as ``ErrorMessages.RESOURCE_NOT_FOUND`` so
the API never advertises which origins it actually trusts. CORS is then
layered on top for browser-friendly preflights from allowlisted origins.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.messages.error_message import ErrorMessages


def register_middleware(app: FastAPI) -> None:
    """Wire host validation, security headers, the origin check and CORS."""

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        """Attach baseline security headers to every response.

        Uses ``frame-ancestors 'none'`` rather than a full ``default-src``
        policy so the bundled Swagger UI keeps loading its assets. HSTS is
        only sent outside local since it requires HTTPS to be meaningful.
        """
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        if settings.ENVIRONMENT != "local":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        return response

    @app.middleware("http")
    async def origin_check_middleware(request: Request, call_next):
        """Strict origin check.

        Returns 404 for unauthorised origins, allows same-origin requests
        (from the API's own origin), and hides error details so the API
        never confirms which origins are allowed.
        """
        origin = request.headers.get("origin")
        if origin:
            origin = origin.rstrip("/")

        # Allow same-origin requests
        if origin:
            scheme = request.url.scheme
            host = request.headers.get("host", "").rstrip("/")
            request_origin = f"{scheme}://{host}".rstrip("/")

            if origin == request_origin:
                return await call_next(request)

        allowed_origins = settings.all_cors_origins

        if origin and allowed_origins and "*" not in allowed_origins:
            if origin not in allowed_origins:
                return JSONResponse(
                    status_code=404,
                    content={
                        "success": False,
                        "error": ErrorMessages.RESOURCE_NOT_FOUND,
                    },
                )
        return await call_next(request)

    # ``allow_credentials=True`` combined with the ``"*"`` wildcard origin
    # is unsafe — some browsers honour it and would let any origin issue
    # authenticated requests. Refuse that combination outright.
    if settings.all_cors_origins:
        if "*" in settings.all_cors_origins:
            raise RuntimeError(
                "CORS misconfiguration: wildcard origin '*' cannot be combined "
                "with credentialed requests. Set explicit origins in "
                "BACKEND_CORS_ORIGINS / FRONTEND_HOST."
            )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.all_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Reject requests whose Host header is not in the allowlist. In production
    # this blocks Host-header injection / cache-poisoning; elsewhere the list
    # resolves to ``["*"]`` so it is a no-op for local dev and tests.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
