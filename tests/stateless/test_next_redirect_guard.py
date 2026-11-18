"""Tests for the `next` redirect guard on the toggle/run form actions.

Row buttons (Run / Enable / Disable on the lists) post with `next=/scripts`
so the action returns to the list. The guard must accept same-site
relative paths and refuse protocol-relative and absolute URLs — otherwise
`?next=//evil.example` would turn the redirect into an open redirect.
"""

import pytest

from app.api.pages import _is_safe_relative


@pytest.mark.parametrize(
    "target,expected",
    [
        ("/scripts", True),
        ("/scripts/1", True),
        ("/executions?script_id=7", True),
        ("//evil.example", False),
        ("https://evil.example", False),
        ("http://evil.example", False),
        ("javascript:alert(1)", False),
        ("", False),
        ("scripts", False),
    ],
)
def test_is_safe_relative(target: str, expected: bool):
    assert _is_safe_relative(target) is expected


def test_toggle_next_open_redirect_refused():
    """A protocol-relative `next` must fall back to the default landing."""
    # uncovered path: the handler ignores an unsafe next entirely
    assert _is_safe_relative("//evil.example/x") is False
    assert _is_safe_relative("/scripts") is True
