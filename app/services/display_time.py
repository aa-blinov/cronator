"""Render stored UTC timestamps in the operator's display timezone.

Everything in the app stores UTC and the scheduler fires in UTC — that
contract does not move. This module is display only: it converts a stored
timestamp to the configured `display_timezone` for the HTML pages and
labels the result with the zone, so a timestamp is never again mistaken
for local time by an operator in a non-UTC zone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_DISPLAY_TIMEZONE = "UTC"


def resolve_display_timezone(name: str | None) -> ZoneInfo:
    """ZoneInfo for a setting value, falling back to UTC.

    An operator can type anything into the settings field; a typo must not
    take every page render down with it.
    """
    name = (name or "").strip()
    if not name or name == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        logger.warning("Unknown display timezone %r — rendering in UTC", name)
        return UTC


def format_in_display_tz(
    value: datetime | None,
    tz_name: str | None = DEFAULT_DISPLAY_TIMEZONE,
    fmt: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    """Format a stored UTC timestamp in the display timezone.

    Naive values are treated as UTC — SQLite (dev and tests) drops tzinfo
    even on timezone(True) columns, and every stored value is UTC by
    contract. None renders as an em dash like the templates already did.
    """
    if value is None:
        return "—"

    tz = resolve_display_timezone(tz_name)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    local = value.astimezone(tz)
    # %Z names the zone the reader is looking at — "UTC" included, so every
    # rendered timestamp carries its zone instead of only some pages.
    rendered = local.strftime(f"{fmt} %Z")
    return rendered.rstrip()
