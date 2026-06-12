"""Tiny User-Agent parser — browser and OS names for the sessions UI.

Deliberately heuristic and dependency-free: the sessions screen only needs a
human-recognizable label ("Chrome on Windows"), not full device analytics.
Order matters in both tables — e.g. Edge and Opera embed ``Chrome/`` in their
UA, so they must be tested first.
"""

from __future__ import annotations

from typing import NamedTuple


class ParsedUserAgent(NamedTuple):
    """Browser and OS display names extracted from a raw User-Agent."""

    browser: str | None
    os: str | None


# (needle, display name) — first match wins.
_BROWSERS: tuple[tuple[str, str], ...] = (
    ("edg", "Edge"),
    ("opr/", "Opera"),
    ("opera", "Opera"),
    ("samsungbrowser", "Samsung Internet"),
    ("firefox", "Firefox"),
    ("chrome", "Chrome"),
    ("crios", "Chrome"),
    ("fxios", "Firefox"),
    ("safari", "Safari"),
)

_OSES: tuple[tuple[str, str], ...] = (
    ("windows", "Windows"),
    ("android", "Android"),
    ("iphone", "iOS"),
    ("ipad", "iPadOS"),
    ("mac os x", "macOS"),
    ("macintosh", "macOS"),
    ("cros", "ChromeOS"),
    ("linux", "Linux"),
)


def parse_user_agent(user_agent: str | None) -> ParsedUserAgent:
    """Extract (browser, os) display names from a raw User-Agent header.

    Unknown or missing values come back as ``None`` so the UI can fall back
    to a generic "Unknown device" label.
    """
    if not user_agent:
        return ParsedUserAgent(browser=None, os=None)

    ua = user_agent.lower()

    browser = next((name for needle, name in _BROWSERS if needle in ua), None)
    os = next((name for needle, name in _OSES if needle in ua), None)
    return ParsedUserAgent(browser=browser, os=os)
