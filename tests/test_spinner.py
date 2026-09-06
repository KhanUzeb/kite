"""WaitSpinner teardown — no stderr daemon leaks under pytest."""

from __future__ import annotations

from io import StringIO

from kite.ui.spinner import WaitSpinner, stop_all_spinners


def test_start_under_pytest_skips_daemon_thread() -> None:
    buf = StringIO()
    spinner = WaitSpinner(stream=buf, delay=0.01)
    spinner.start()
    assert spinner._thread is None
    spinner.kick("working")
    stop_all_spinners()
    assert spinner._thread is None
