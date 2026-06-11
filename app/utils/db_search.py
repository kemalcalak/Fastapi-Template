"""Helpers for building safe SQL ``LIKE`` / ``ILIKE`` search patterns."""

# Escape character paired with every ``.ilike(pattern, escape=LIKE_ESCAPE_CHAR)``
# call so the neutralised wildcards below are interpreted literally.
LIKE_ESCAPE_CHAR = "\\"


def ilike_contains(term: str) -> str:
    """Return a ``%term%`` pattern with ``LIKE`` wildcards in ``term`` neutralised.

    Escapes the backslash escape character first, then ``%`` and ``_`` so a
    user searching for a literal ``50%`` or ``a_b`` does not turn those into
    wildcards — which would otherwise cause over-broad matches and needless
    full scans. Callers MUST pass ``escape=LIKE_ESCAPE_CHAR`` to ``.ilike()``.
    """
    escaped = (
        term.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR * 2)
        .replace("%", LIKE_ESCAPE_CHAR + "%")
        .replace("_", LIKE_ESCAPE_CHAR + "_")
    )
    return f"%{escaped}%"
