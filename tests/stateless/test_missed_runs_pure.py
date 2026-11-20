"""Pure parts of missed-run detection: cron parsing and fire-time iteration."""

from datetime import UTC, datetime

from app.services.missed_runs import iter_expected_fires
from app.services.scheduler import parse_cron_expression


class TestParseCronExpression:
    def test_valid_expression_returns_trigger(self):
        assert parse_cron_expression("0 3 * * *") is not None

    def test_wrong_field_count_returns_none(self):
        assert parse_cron_expression("0 3 * *") is None
        assert parse_cron_expression("0 3 * * * *") is None

    def test_unparseable_field_returns_none(self):
        assert parse_cron_expression("not-a-cron * * * *") is None


class TestIterExpectedFires:
    def test_every_15_minutes_in_an_hour(self):
        trigger = parse_cron_expression("*/15 * * * *")
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        end = datetime(2026, 11, 20, 11, 0, tzinfo=UTC)

        fires = list(iter_expected_fires(trigger, start, end))

        assert [f.minute for f in fires] == [0, 15, 30, 45, 0]
        assert all(f.tzinfo is not None for f in fires)

    def test_daily_fire_inside_a_24h_window(self):
        trigger = parse_cron_expression("0 3 * * *")
        start = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
        end = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)

        fires = list(iter_expected_fires(trigger, start, end))

        assert len(fires) == 1
        assert fires[0].hour == 3 and fires[0].day == 21

    def test_window_without_any_fire_is_empty(self):
        trigger = parse_cron_expression("0 9 * * *")
        # Window that ends before the only daily moment.
        start = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        end = datetime(2026, 11, 20, 10, 30, tzinfo=UTC)

        assert list(iter_expected_fires(trigger, start, end)) == []

    def test_window_end_is_inclusive(self):
        trigger = parse_cron_expression("0 10 * * *")
        start = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
        end = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)

        fires = list(iter_expected_fires(trigger, start, end))

        assert len(fires) == 1
        assert fires[0] == end
