"""Missed-schedule detection.

PRODUCT.md principle 2: "Every run leaves a record… A failure that leaves no
row is a bug." A schedule that never fired leaves no row at all — the
process was down at the cron moment, APScheduler jobs live in memory
(`add_job` with no persistent jobstore), so after a restart the missed
moment is unknown to the scheduler, and until now nothing surfaced it
except the seven-day dashboard heuristic.

This service closes that loop: it recomputes the expected fire times from
each enabled script's cron expression and stores an execution row with
status "missed" for every expected moment that has no execution row within
its coverage window. A persisted cursor (settings key `missed_runs_cursor`)
makes the sweep incremental and covers downtime — the cursor survives the
restart, so on boot the sweep sees the entire gap at once.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import async_session_maker
from app.models.execution import Execution, ExecutionStatus
from app.models.script import Script
from app.services.scheduler import parse_cron_expression

logger = logging.getLogger(__name__)

# Settings-table key holding the ISO timestamp of the last swept moment.
CURSOR_KEY = "missed_runs_cursor"

# The sweep never looks at the last two minutes: a fire from a minute ago may
# still be starting, and a row that appears a second later would otherwise
# turn the sweep's own "missed" record into a false alarm.
SWEEP_BUFFER = timedelta(seconds=120)

# Never look back further than this — after months of downtime the detector
# must not flood the history table with tens of thousands of rows; the
# seven-day dashboard heuristic already covers that scale.
MAX_LOOKBACK = timedelta(days=7)

# A run started slightly before its scheduled moment still counts as the
# scheduled run happening (clock drift, executor start latency).
COVERAGE_BEFORE = timedelta(seconds=60)

# Per-script cap on recorded misses in a single sweep. Hit only by an
# every-minute script after a long downtime; truncation is logged.
MAX_RECORDED_PER_SCRIPT = 500

# The failure alert is throttled to one per hour in the executor; a sweep
# that found many misses must not become a mail storm.
_FAILURE_ALERT_THROTTLE = timedelta(seconds=3600)


def iter_expected_fires(trigger: CronTrigger, start: datetime, end: datetime) -> Iterator[datetime]:
    """Yield every fire time of `trigger` in [start, end], in order."""
    fire = trigger.get_next_fire_time(None, start)
    while fire is not None and fire <= end:
        yield fire
        fire = trigger.get_next_fire_time(fire, fire)


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite (used in tests) drops tzinfo even on timezone(True) columns."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def detect_missed_runs(now: datetime | None = None) -> int:
    """Record an execution row (status "missed") for every expected cron
    fire that has no execution row within its coverage window.

    Returns the number of rows created. Advances the persisted cursor to the
    end of the swept window even when it found nothing, so the next sweep
    starts where this one ended.
    """
    from app.services.metrics import record_execution_status
    from app.services.settings_service import settings_service

    now = _as_utc(now) or datetime.now(UTC)
    window_end = now - SWEEP_BUFFER

    cursor_raw = await settings_service.get(CURSOR_KEY, "")
    window_start = _as_utc(_parse_iso(cursor_raw)) or window_end

    lookback_floor = window_end - MAX_LOOKBACK
    if window_start < lookback_floor:
        window_start = lookback_floor

    created = 0
    async with async_session_maker() as db:
        scripts = (await db.execute(select(Script).where(Script.enabled))).scalars().all()

        for script in scripts:
            trigger = parse_cron_expression(script.cron_expression)
            if trigger is None:
                # add_job logs the same error; the detector just skips what
                # the scheduler itself cannot run.
                continue

            created_for_script = 0
            truncated = False
            for fire in iter_expected_fires(trigger, window_start, window_end):
                # A fire before the script existed is not a missed run —
                # the cursor is global, not per-script.
                if _as_utc(script.created_at) and fire < _as_utc(script.created_at):
                    continue

                tolerance = timedelta(seconds=max(script.misfire_grace_time, 60))
                covered = await db.scalar(
                    select(Execution.id)
                    .where(
                        Execution.script_id == script.id,
                        Execution.started_at >= fire - COVERAGE_BEFORE,
                        Execution.started_at <= fire + tolerance,
                    )
                    .limit(1)
                )
                if covered:
                    continue

                db.add(
                    Execution(
                        script_id=script.id,
                        status=ExecutionStatus.MISSED.value,
                        started_at=fire,
                        finished_at=fire,
                        duration_ms=0,
                        triggered_by="scheduler",
                        error_message=(
                            "Missed schedule: no execution recorded for the "
                            f"expected run at {fire.isoformat()}"
                        ),
                    )
                )
                created += 1
                created_for_script += 1
                record_execution_status(ExecutionStatus.MISSED.value, triggered_by="scheduler")

                if created_for_script >= MAX_RECORDED_PER_SCRIPT:
                    truncated = True
                    break

            if truncated:
                logger.warning(
                    "Missed-run sweep truncated at %d fires for script %s — "
                    "the downtime window exceeds MAX_LOOKBACK expectations",
                    MAX_RECORDED_PER_SCRIPT,
                    script.name,
                )

            if created_for_script and script.alert_on_failure:
                await _alert_missed(db, script, now)

        await db.commit()

    await settings_service.set(CURSOR_KEY, window_end.isoformat())

    if created:
        logger.warning("Missed-run sweep recorded %d missed schedule(s)", created)
    return created


async def _alert_missed(db, script: Script, now: datetime) -> None:
    """Send one failure alert for a script with newly recorded misses.

    Reuses the failure-alert path (same subject line, same throttle column)
    so the operator's inbox treats a missed schedule like the failure it is.
    The throttle check mirrors executor._send_failure_alert: one hour per
    script, judged against last_failure_alert_at specifically.
    """
    from app.services.alerting import alerting_service

    last_alert = _as_utc(script.last_failure_alert_at)
    if last_alert and (now - last_alert) < _FAILURE_ALERT_THROTTLE:
        return

    missed = await db.scalar(
        select(Execution)
        .where(
            Execution.script_id == script.id,
            Execution.status == ExecutionStatus.MISSED.value,
        )
        .order_by(Execution.started_at.desc())
        .limit(1)
    )
    if missed is None:
        return

    await alerting_service.send_failure_alert(script, missed)
    # Same visibility contract as the executor: a delivery failure must
    # land on the script row, not only in the log.
    errors = alerting_service.take_delivery_errors()
    if errors:
        script.last_alert_error = "; ".join(errors)[:500]
        script.last_alert_error_at = now
    else:
        script.last_alert_error = None
        script.last_alert_error_at = None
    script.last_failure_alert_at = now
    script.last_alert_at = now


def _parse_iso(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
