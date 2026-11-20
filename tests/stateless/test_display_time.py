"""Display-timezone rendering: storage stays UTC, only the shown time moves."""

from datetime import UTC, datetime

from app.services.display_time import (
    DEFAULT_DISPLAY_TIMEZONE,
    format_in_display_tz,
    resolve_display_timezone,
)


class TestResolveDisplayTimezone:
    def test_utc_and_empty_fall_back_to_utc(self):
        assert str(resolve_display_timezone("UTC")) == "UTC"
        assert str(resolve_display_timezone("")) == "UTC"
        assert str(resolve_display_timezone(None)) == "UTC"

    def test_iana_name_resolves(self):
        assert resolve_display_timezone("Europe/Moscow").key == "Europe/Moscow"

    def test_unknown_name_falls_back_to_utc(self):
        # An operator typo must not take page rendering down with it.
        assert str(resolve_display_timezone("Not/AZone")) == "UTC"


class TestFormatInDisplayTz:
    def test_utc_value_stays_utc_and_says_so(self):
        value = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
        assert format_in_display_tz(value, "UTC") == "2026-11-20 12:00:00 UTC"

    def test_utc_value_converted_to_display_zone(self):
        value = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
        # Moscow is UTC+3 in November (no DST since 2014).
        assert format_in_display_tz(value, "Europe/Moscow") == "2026-11-20 15:00:00 MSK"

    def test_naive_value_is_treated_as_utc(self):
        # SQLite (dev and tests) drops tzinfo even on timezone(True) columns.
        value = datetime(2026, 11, 20, 12, 0, 0)
        assert format_in_display_tz(value, "Europe/Moscow") == "2026-11-20 15:00:00 MSK"

    def test_none_renders_as_dash(self):
        assert format_in_display_tz(None, DEFAULT_DISPLAY_TIMEZONE) == "—"

    def test_custom_format_is_respected(self):
        value = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
        assert format_in_display_tz(value, "UTC", "%H:%M") == "12:00 UTC"

    def test_unknown_zone_falls_back_to_utc(self):
        value = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
        assert format_in_display_tz(value, "Not/AZone") == "2026-11-20 12:00:00 UTC"
