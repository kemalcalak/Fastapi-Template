"""Prometheus metrics: instrumentation and the gated /metrics endpoint.

Two responsibilities live here so ``main.py`` stays uncluttered:

1. ``prometheus-fastapi-instrumentator`` collects per-request metrics
   (count, latency histogram, in-progress gauge, exceptions per handler)
   plus the standard Python runtime metrics from ``prometheus_client``.
2. The ``/metrics`` endpoint exposes them in the standard Prometheus
   exposition format. Local dev keeps it open; every other environment
   requires a bearer token (``METRICS_TOKEN``). Mismatched / missing
   tokens return 404 — mirrors ``origin_check_middleware`` so the
   endpoint's existence is not disclosed to outsiders.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi import Header
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    generate_latest,
    multiprocess,
)
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.exceptions import HTTPException

from app.core.config import settings
from app.core.messages.error_message import ErrorMessages

if TYPE_CHECKING:
    from fastapi import FastAPI


def init_metrics(app: FastAPI) -> None:
    """Wire Prometheus instrumentation and register the /metrics route."""
    # Health and /metrics itself are excluded from instrumentation to keep
    # noise out of the time series.
    Instrumentator(
        excluded_handlers=["/metrics", f"{settings.API_V1_STR}/health/.*"],
    ).instrument(app)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(
        authorization: str | None = Header(default=None),
    ) -> Response:
        """Expose Prometheus metrics in the standard exposition format.

        Local dev keeps the endpoint open for convenience. In every other
        environment a bearer token (``METRICS_TOKEN``) is required;
        mismatched or missing tokens return 404 to avoid disclosing the
        endpoint to outsiders.
        """
        if settings.ENVIRONMENT != "local":
            expected = (
                f"Bearer {settings.METRICS_TOKEN}" if settings.METRICS_TOKEN else None
            )
            if expected is None or authorization != expected:
                raise HTTPException(
                    status_code=404,
                    detail=ErrorMessages.RESOURCE_NOT_FOUND,
                )

        # Under multiple workers (PROMETHEUS_MULTIPROC_DIR set), each process
        # writes to its own file; aggregate them via MultiProcessCollector so
        # /metrics returns combined counts instead of one worker's slice.
        if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            payload = generate_latest(registry)
        else:
            payload = generate_latest()
        return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
