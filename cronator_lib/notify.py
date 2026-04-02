"""Manual notification support for Cronator scripts."""

import os
import sys


# Marker parsed by the executor to trigger an email alert
_NOTIFY_MARKER = "CRONATOR_NOTIFY:"


def notify(message: str, *, title: str | None = None) -> None:
    """
    Send a manual notification from within a script.

    Inside Cronator: prints a special marker that the executor catches
    and forwards as an email alert (uses the same SMTP settings as
    automatic failure/success alerts).

    Outside Cronator (local dev): prints to stdout so the message is
    visible during local testing.

    Args:
        message: Notification body text.
        title:   Optional subject prefix. Defaults to the script name.

    Example:
        from cronator_lib import notify

        rows = export_to_csv()
        notify(f"Export complete: {rows} rows written")

        # With custom title:
        notify("Disk usage above 90%", title="Warning")
    """
    script_name = os.environ.get("CRONATOR_SCRIPT_NAME", "cronator_script")
    effective_title = title or script_name

    payload = f"{effective_title}|{message}"
    print(f"{_NOTIFY_MARKER}{payload}", flush=True)
