"""Shared schema primitives used across multiple domains."""

from __future__ import annotations

from pydantic import JsonValue

__all__ = ["JsonValue", "ActivityDetails"]

# Structured audit-log payload — a JSON object with typed leaf values.
# Any value representable in JSON is accepted, so callers can pass plain
# dicts (``{"reason": "invalid_password"}``) without ceremony.
ActivityDetails = dict[str, JsonValue]
