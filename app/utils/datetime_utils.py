from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current datetime in UTC timezone."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Coerce a datetime to UTC-aware.

    DB backends that drop tzinfo (SQLite in tests) hand back naive datetimes
    even for ``DateTime(timezone=True)`` columns; those are stored in UTC, so
    attaching UTC restores the original instant for safe comparisons.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
