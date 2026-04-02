"""Cronator execution context — metadata about the current script run."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CronatorContext:
    """
    Immutable snapshot of the current execution environment.

    Available inside scripts running under Cronator.
    Outside Cronator (local dev) all IDs are None and is_cronator=False.

    Example:
        from cronator_lib import get_context

        ctx = get_context()
        if ctx.is_cronator:
            log.info(f"Running as execution #{ctx.execution_id}")
    """

    script_id: int | None
    execution_id: int | None
    script_name: str
    artifacts_dir: Path | None
    is_cronator: bool

    @classmethod
    def current(cls) -> "CronatorContext":
        """Build context from environment variables set by the executor."""
        execution_id_str = os.environ.get("CRONATOR_EXECUTION_ID")
        script_id_str = os.environ.get("CRONATOR_SCRIPT_ID")
        artifacts_dir_str = os.environ.get("CRONATOR_ARTIFACTS_DIR")

        execution_id = int(execution_id_str) if execution_id_str else None
        script_id = int(script_id_str) if script_id_str else None
        artifacts_dir = Path(artifacts_dir_str) if artifacts_dir_str else None
        script_name = os.environ.get("CRONATOR_SCRIPT_NAME", "")
        is_cronator = execution_id is not None

        return cls(
            script_id=script_id,
            execution_id=execution_id,
            script_name=script_name,
            artifacts_dir=artifacts_dir,
            is_cronator=is_cronator,
        )


def get_context() -> CronatorContext:
    """
    Return the current execution context.

    Example:
        from cronator_lib import get_context

        ctx = get_context()
        print(ctx.script_name)   # "my_report"
        print(ctx.execution_id)  # 42
    """
    return CronatorContext.current()
