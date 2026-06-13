"""Schemas used by background-worker jobs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DeletionJobResult(BaseModel):
    """Outcome of a single run of the expired-account deletion job."""

    processed: int = Field(ge=0, description="Users hard-deleted this run.")
    failed: int = Field(ge=0, description="Users that errored and will be retried.")
    duration_ms: int = Field(ge=0, description="Total wall-clock time in ms.")


class SessionPurgeJobResult(BaseModel):
    """Outcome of a single run of the stale-session purge job."""

    purged: int = Field(ge=0, description="Session rows deleted this run.")
    duration_ms: int = Field(ge=0, description="Total wall-clock time in ms.")
