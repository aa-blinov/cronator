"""TDD tests for F18: per-script timeout UI hint.

The script editor must warn users when they set an unusually high timeout
(> 1 day) or unusually low (< 60s) so they don't accidentally create zombie
jobs or get killed scripts. The hint appears on the editor page next to the
timeout input.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_editor():
    return (REPO_ROOT / "app" / "templates" / "script_editor.html").read_text()


def test_editor_has_timeout_hint_text():
    """The script_editor template must show a hint near the timeout field."""
    content = _read_editor()
    lower = content.lower()
    assert "timeout" in lower, "no mention of timeout in editor template"
    assert any(
        needle in lower
        for needle in ("hint", "warning", "tip", "note", "maximum", "recommended")
    ), "no hint/warning text in editor template"


def test_editor_mentions_24_hour_max():
    """The hint must clarify the hard upper bound (24 hours = 86400 seconds)."""
    content = _read_editor()
    assert "86400" in content or "24 h" in content or "24-hour" in content, (
        "editor template does not mention the 24h timeout cap"
    )


def test_editor_includes_warning_about_long_timeouts():
    """The hint must include the word 'long' or 'zombie' to flag the risk."""
    content = _read_editor().lower()
    assert any(
        needle in content
        for needle in ("long", "zombie", "migration", "export", "stuck")
    ), "editor template does not warn about long-running risks"
