from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["ok", "timeout", "unavailable"]
ReadinessStatus = Literal["ready", "not_ready"]


class CheckResult(BaseModel):
    status: CheckStatus
    latency_ms: float | None = Field(default=None, ge=0)


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"
    version: str


class ReadinessResponse(BaseModel):
    status: ReadinessStatus
    version: str
    checks: dict[str, CheckResult]
