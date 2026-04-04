"""Timer context manager for measuring and logging code block duration."""

import json
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Generator

from cronator_lib.logging import get_logger


@contextmanager
def timer(label: str = "", logger=None) -> Generator[dict, None, None]:
    """
    Context manager that measures elapsed time of a code block and logs it.

    Args:
        label:  Human-readable name for the timed block.
        logger: CronatorLogger instance. If None, uses get_logger().

    Yields:
        dict with key "elapsed" (float seconds), populated on exit.

    Example:
        from cronator_lib import timer

        with timer("load data"):
            df = load_csv("big_file.csv")
        # → INFO [load data] completed in 3.42s

        # Access elapsed time:
        with timer("query") as t:
            results = db.execute(sql)
        print(f"Query took {t['elapsed']:.2f}s")
    """
    if logger is None:
        logger = get_logger()

    result: dict = {"elapsed": 0.0}
    start = time.perf_counter()

    try:
        yield result
    finally:
        result["elapsed"] = time.perf_counter() - start
        elapsed = result["elapsed"]

        if elapsed < 1:
            formatted = f"{elapsed * 1000:.0f}ms"
        elif elapsed < 60:
            formatted = f"{elapsed:.2f}s"
        else:
            minutes = int(elapsed // 60)
            seconds = elapsed % 60
            formatted = f"{minutes}m {seconds:.0f}s"

        msg = f"[{label}] completed in {formatted}" if label else f"Completed in {formatted}"

        if os.environ.get("CRONATOR_EXECUTION_ID"):
            # In Cronator context — emit JSON with TIMER level so UI renders it distinctly
            print(
                json.dumps({
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "TIMER",
                    "message": msg,
                    "logger": "cronator.timer",
                }, ensure_ascii=False),
                flush=True,
            )
        else:
            # Local dev — use regular logger
            logger.info(msg)
