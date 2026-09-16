"""Prometheus metrics service for F6.

Exposes a tiny set of gauges/counters without taking a hard dependency on
`prometheus_client`. The format is the standard text exposition format so
any Prometheus-compatible scraper (Prometheus, VictoriaMetrics, Grafana Agent,
OpenTelemetry collector) can consume it.

Metrics exposed:
- crinator_app_info{version="..."}  — constant 1, identifies the running version
- crinator_uptime_seconds           — seconds since the app started
- crinator_scripts_total             — total number of scripts registered
- crinator_executions_total{status}  — counter of historical executions by status
- crinator_executions_running        — gauge of currently-running executions
- crinator_scheduler_jobs            — gauge of registered scheduler jobs
- crinator_artifacts_total           — gauge of artifact rows
"""

from __future__ import annotations

import time
from collections import Counter
from threading import Lock
from typing import Iterable

from app import __version__


class MetricsRegistry:
    """Minimal in-memory metrics registry.

    Supports:
    - Counter (monotonically increasing values, optionally labeled)
    - Gauge (current value, optionally labeled)

    Lock-protected because metrics can be updated from concurrent requests.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        # Metric metadata
        self._help: dict[str, str] = {}
        self._types: dict[str, str] = {}

    def register_counter(self, name: str, help_text: str) -> None:
        with self._lock:
            self._help[name] = help_text
            self._types[name] = "counter"

    def register_gauge(self, name: str, help_text: str) -> None:
        with self._lock:
            self._help[name] = help_text
            self._types[name] = "gauge"

    def counter_inc(self, name: str, value: float = 1.0, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def gauge_set(self, name: str, value: float, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = float(value)

    @staticmethod
    def _key(name: str, labels: dict | None) -> tuple[str, tuple[tuple[str, str], ...]]:
        if not labels:
            return (name, ())
        # Sort labels for stability
        return (name, tuple(sorted(labels.items())))

    def render(self) -> str:
        """Render in Prometheus text exposition format."""
        out: list[str] = []
        with self._lock:
            seen: set[str] = set()
            all_metrics: dict[str, dict] = {}
            for (name, label_pairs), value in self._counters.items():
                all_metrics.setdefault(name, {"type": "counter", "samples": []})
                all_metrics[name]["samples"].append((label_pairs, value))
            for (name, label_pairs), value in self._gauges.items():
                all_metrics.setdefault(name, {"type": "gauge", "samples": []})
                all_metrics[name]["samples"].append((label_pairs, value))
            for name in all_metrics:
                if name in seen:
                    continue
                seen.add(name)
                out.append(f"# HELP {name} {self._help.get(name, '')}")
                out.append(f"# TYPE {name} {self._types.get(name, all_metrics[name]['type'])}")
                for label_pairs, value in all_metrics[name]["samples"]:
                    label_str = ""
                    if label_pairs:
                        label_str = "{" + ",".join(f'{k}="{v}"' for k, v in label_pairs) + "}"
                    out.append(f"{name}{label_str} {value}")
        return "\n".join(out) + "\n"


# Module-level singleton
metrics_registry = MetricsRegistry()

# Register metrics with help text
metrics_registry.register_counter(
    "crinator_executions_total",
    "Total number of executions since process start, labeled by status.",
)
metrics_registry.register_gauge(
    "crinator_app_info",
    "Constant 1; labels carry identifying metadata (version).",
)
metrics_registry.register_gauge(
    "crinator_uptime_seconds",
    "Seconds elapsed since the app started.",
)
metrics_registry.register_gauge(
    "crinator_scripts_total",
    "Total number of scripts registered in the database.",
)
metrics_registry.register_gauge(
    "crinator_executions_running",
    "Number of executions currently in RUNNING state.",
)
metrics_registry.register_gauge(
    "crinator_scheduler_jobs",
    "Number of jobs currently registered with the scheduler.",
)
metrics_registry.register_gauge(
    "crinator_artifacts_total",
    "Total number of artifact rows across all executions.",
)


_APP_START_TIME = time.monotonic()


def get_uptime_seconds() -> float:
    return time.monotonic() - _APP_START_TIME


def record_execution_status(status: str, triggered_by: str | None = None) -> None:
    """Increment the executions_total counter for a finished execution."""
    labels = {"status": status}
    if triggered_by:
        labels["triggered_by"] = triggered_by
    metrics_registry.counter_inc("crinator_executions_total", labels=labels)


def init_app_info(version: str | None = None) -> None:
    metrics_registry.gauge_set("crinator_app_info", 1.0, labels={"version": version or __version__})
