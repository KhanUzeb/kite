"""Retrieval of what the scroll path truncated — `/last` and honest markers.

The scroll printer caps every tool body at PREVIEW_LINES rows and only names a
command. If that command does not exist (it used to be `/diff`), the hint is a
lie; if it names `/expand`, it is a lie too — /expand flips state for FUTURE
calls and never re-prints what already scrolled past. These tests pin both
halves: the marker must name a registered builtin, and `/last` must give the
rows back.
"""

from __future__ import annotations

import re
from io import StringIO

from rich.console import Console
from rich.text import Text

from kite.agent.events import Event
from kite.ui import commands as commands_mod
from kite.ui.commands import BUILTINS
from kite.ui.diff import make_unified_diff
from kite.ui.output_view import format_viewable_output
from kite.ui.render import RunDisplay
from kite.ui.state import SessionUiState
from kite.ui.style import KITE_THEME, PREVIEW_LINES
from kite.ui.tool_cards import render_bash_command_block, render_code_edit_preview
from tests.conftest import strip_ansi

_REGISTERED = frozenset(b.name for b in BUILTINS) | frozenset(commands_mod.ALIASES)
_HINT_RE = re.compile(r"/([A-Za-z][\w-]*)")


def _display(width: int = 120) -> tuple[RunDisplay, StringIO]:
    """A RunDisplay whose console writes to an in-memory buffer."""
    buf = StringIO()
    console = Console(file=buf, width=width, force_terminal=True, theme=KITE_THEME)
    return RunDisplay(console, state=SessionUiState(), quiet=False), buf


class _Repl:
    """The one method /last needs from the REPL, without building the real one."""

    def __init__(self, display: RunDisplay, buf: StringIO) -> None:
        from kite.ui.repl import ChatSession

        self.display = display
        self.console = display.console
        self.state = display.state
        self._slash_last = ChatSession._slash_last.__get__(self)


def _retrieved(display: RunDisplay, buf: StringIO) -> str:
    """Run /last against `display` and return just what it painted.

    The buffer is wiped first: it still holds the scroll-path rows, and this
    suite asserts on the retrieval output alone.
    """
    buf.truncate(0)
    buf.seek(0)
    _Repl(display, buf)._slash_last("")
    return strip_ansi(buf.getvalue())


def _big_diff(rows: int = 60) -> str:
    before = "".join(f"line {i}\n" for i in range(rows))
    after = "".join(f"line {i} edited\n" for i in range(rows))
    return make_unified_diff("src/app.py", before, after)


def test_last_reprints_every_row_a_capped_body_hid() -> None:
    """A 30-line body prints 5 on scroll; /last gives back all 30."""
    assert PREVIEW_LINES == 5
    display, buf = _display()
    display.state.expanded_all = False  # the capped-scroll path (default is expanded)
    output = "\n".join(f"result line {i:02d}" for i in range(30))
    display(Event("tool_end", payload={"tool": "bash", "ok": True, "output": output}))
    display.close()

    scrolled = strip_ansi(buf.getvalue())
    rows = [ln for ln in scrolled.splitlines() if "result line" in ln]
    assert len(rows) == PREVIEW_LINES, rows
    assert "result line 29" not in scrolled, "the tail must be hidden on the scroll path"

    # The retrieval half: same record, printed through /last.
    again, again_buf = _display()
    again.state.expanded_all = False
    again(Event("tool_end", payload={"tool": "bash", "ok": True, "output": output}))
    again.close()
    plain = _retrieved(again, again_buf)

    got = [ln for ln in plain.splitlines() if "result line" in ln]
    assert len(got) == 30, got
    assert "result line 00" in plain and "result line 29" in plain
    # A header names the call so the block is identifiable when scrolled back to.
    assert "bash" in plain and "ok" in plain


def test_last_renders_the_diff_uncollapsed_and_read_only() -> None:
    """A capped diff comes back whole, and nothing about the state moves."""
    assert PREVIEW_LINES == 5
    diff = _big_diff()
    display, buf = _display()
    display.state.expanded_all = False
    display(Event("tool_end", payload={"tool": "edit", "ok": True, "diff": diff}))
    display.close()

    scrolled = strip_ansi(buf.getvalue())
    assert "line 50" not in scrolled, "the scroll path must stay capped"
    assert "+60,-60" in scrolled

    again, again_buf = _display()
    again.state.expanded_all = False
    again(Event("tool_end", payload={"tool": "edit", "ok": True, "diff": diff}))
    before = (again.state.expanded_all, again.state.todos, again.state.cost)
    again.close()
    plain = _retrieved(again, again_buf)

    # Uncollapsed: rows past the cap are present, which is the whole point.
    assert "line 50" in plain and "line 59" in plain, "the diff must come back whole"
    assert "+60,-60" in plain and "src/app.py" in plain
    # Read-only: no state mutation, and no /expand-style cap marker.
    assert (again.state.expanded_all, again.state.todos, again.state.cost) == before
    assert "+25 lines" not in plain

    # A body is rendered through the existing formatter, not a second path.
    assert format_viewable_output("a\nb\n") .strip() == "a\nb"


def test_overflow_markers_only_name_registered_commands() -> None:
    """The regression guard: a marker may never name a command that is absent.

    This is what let `/diff` ship — the hint read well and resolved to
    `unknown command /diff`. Every command a marker names is cross-checked
    against BUILTINS, so reintroducing a phantom fails here.
    """
    write = render_code_edit_preview("write", {"path": "a.py", "content": "\n".join(f"l{i}" for i in range(20))})
    edit = render_code_edit_preview(
        "edit",
        {
            "path": "a.py",
            "old_string": "\n".join(f"o{i}" for i in range(20)),
            "new_string": "\n".join(f"n{i}" for i in range(20)),
        },
    )
    bash = render_bash_command_block("\n".join(f"echo {i}" for i in range(20)))
    assert write is not None and edit is not None

    for block in (write, edit, bash):
        plain = block.plain if isinstance(block, Text) else str(block)
        marker = [ln for ln in plain.splitlines() if "lines  /" in ln]
        assert marker, plain
        for row in marker:
            names = _HINT_RE.findall(row.split("lines", 1)[1])
            assert names, row
            for name in names:
                assert name in _REGISTERED, f"phantom command /{name} in: {row!r}"

    # The markers really do name the retrieval command, not /expand: /expand
    # only reshapes future calls and cannot re-print what already scrolled by.
    assert "/last" in write.plain and "/last" in edit.plain
    assert "/last" in bash.plain
    assert "expand" not in bash.plain and "diff" not in bash.plain
    # And /last is dispatchable, not just a hint string.
    assert "last" in commands_mod.CONTROL_COMMANDS
    assert commands_mod.parse_slash("/last").command == "last"


def test_last_with_nothing_captured_says_so() -> None:
    """Nothing has run yet: one clear line, not a crash or a blank screen."""
    display, buf = _display()
    repl = _Repl(display, buf)
    display(Event("agent_start", payload={"task": "hi"}))
    repl._slash_last("")
    plain = strip_ansi(buf.getvalue())
    assert "no tool output yet" in plain, plain
    # An argument is accepted and ignored — /last takes none.
    repl._slash_last("ignored")
    assert "no tool output yet" in strip_ansi(buf.getvalue())


def test_last_reports_failures_and_bounds_the_payload() -> None:
    """A failed call is retrievable, and a runaway body cannot pin memory."""
    display, buf = _display()
    display(
        Event(
            "tool_end",
            payload={"tool": "bash", "ok": False, "error": "boom: exit 2", "output": ""},
        )
    )
    display.close()
    plain = _retrieved(display, buf)
    assert "failed" in plain and "boom: exit 2" in plain, plain

    # The stored payload is capped, and the header says so.
    from kite.ui.render import _LAST_TOOL_CHARS

    big, big_buf = _display()
    big(
        Event(
            "tool_end",
            payload={"tool": "bash", "ok": True, "output": "x" * (_LAST_TOOL_CHARS + 5_000)},
        )
    )
    big.close()
    assert len(big._last_tool_view.output) == _LAST_TOOL_CHARS
    assert big._last_tool_view.truncated is True
    assert "payload capped" in _retrieved(big, big_buf)