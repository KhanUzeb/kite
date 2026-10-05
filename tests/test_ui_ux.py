"""Width-aware UI: nothing wraps at 60-120 cols, and the quiet style stays quiet.

v1.0.6 collapsed the live task list to one line and capped tool bodies at
PREVIEW_LINES. Less clutter, but at 60-80 cols the compact line wrapped
raggedly, the footer ran out of room and spilled onto a second row, and the
overflow markers across write/edit/bash said the same thing three slightly
different ways.

These tests pin three properties:

  * no rendered line exceeds the console width at 60, 80 or 120 cols;
  * narrow is bought by dropping decoration (the progress bar, the family tag,
    a note) and never by deleting the count or the item in flight;
  * the 5-row body budget is still 5 — a narrow terminal is fixed by shaping
    the row, never by printing more of it.

Width is measured the way the terminal measures it: `Console(width=W)` renders
through Rich, and each output row is measured with `rich.cells.cell_len`, so a
double-width glyph counts as 2 exactly as it would on screen.
"""

from __future__ import annotations

import os
import re
import shutil
from io import StringIO

from rich.cells import cell_len
from rich.console import Console

from kite.agent.events import Event
from kite.ui.chips import render_plan_tasks, render_task_row
from kite.ui.render import RunDisplay
from kite.ui.state import SessionUiState, TodoItem
from kite.ui.status import format_status_tail, render_status, status_segments
from kite.ui.style import KITE_THEME, PREVIEW_LINES
from kite.ui.theme import glyph
from kite.ui.tool_cards import (
    ToolCard,
    overflow_marker,
    render_bash_command_block,
    render_code_edit_preview,
    render_parallel_batch_header,
    render_tool_card_done,
    render_tool_card_start,
    render_tool_summary,
)
from tests.conftest import strip_ansi

WIDTHS = (60, 80, 120)


def _display(width: int = 120) -> tuple[RunDisplay, StringIO]:
    """A RunDisplay whose console writes to an in-memory buffer."""
    buf = StringIO()
    console = Console(file=buf, width=width, force_terminal=True, theme=KITE_THEME)
    return RunDisplay(console, state=SessionUiState(), quiet=False), buf


def _at_width(monkeypatch, width: int) -> None:
    """Pin the live terminal width the renderers read, not just the console."""
    monkeypatch.setattr(
        shutil, "get_terminal_size", lambda fallback=None: os.terminal_size((width, 24))
    )


def _render(build, width: int) -> list[str]:
    """Render one Text through a console of ``width`` and return its plain rows."""
    buf = StringIO()
    console = Console(file=buf, width=width, force_terminal=True, theme=KITE_THEME)
    console.print(build())
    return [strip_ansi(row) for row in strip_ansi(buf.getvalue()).splitlines()]


def _overflow(items: list[dict[str, str]]) -> list[TodoItem]:
    return [TodoItem(**item) for item in items]


def _items() -> list[dict[str, str]]:
    """A plan whose in-flight item is long enough to force a real decision."""
    return [
        {"id": "1", "content": "read the diff module", "status": "completed"},
        {
            "id": "2",
            "content": "make the tool card overflow markers consistent and informative",
            "status": "in_progress",
        },
        {"id": "3", "content": "run the full suite", "status": "pending"},
    ]


def _busy_state() -> SessionUiState:
    """Every status segment at once: the segment-soup worst case."""
    state = SessionUiState(provider="groq", model="llama-3.3-70b", cost=0.1234, busy=True)
    state.tokens, state.window = 40_000, 128_000
    state.git_branch = "main"
    state.active_jobs = 1
    state.active_subagents = 2
    return state


def _assert_fits(build, width: int, *, label: str) -> list[str]:
    rows = [row for row in _render(build, width) if row.strip()]
    for row in rows:
        assert cell_len(row) <= width, (
            f"{label} at width {width}: row of {cell_len(row)} columns "
            f"wraps:\n{row!r}"
        )
    return rows


def _c_test_compact_task_line_never_wraps_at_any_width(monkeypatch) -> None:
    """The compact line is one row at 60, 80 and 120 cols — nothing spills."""
    items = _overflow(_items())
    for width in WIDTHS:
        _at_width(monkeypatch, width)
        rows = _assert_fits(lambda: render_plan_tasks(items), width, label="compact task line")
        assert len(rows) == 1, f"the compact line must stay one row, got {rows}"
        assert "Tasks" in rows[0], rows[0]


def _c_test_tool_done_card_never_wraps_at_any_width(monkeypatch) -> None:
    """A done card with timing, a diff stat and a long note stays one row."""
    for width in WIDTHS:
        _at_width(monkeypatch, width)
        rows = _assert_fits(
            lambda: render_tool_card_done(
                "edit",
                ok=True,
                meta="12ms",
                added=412,
                deleted=37,
                summary="applied the edit to src/kite/ui/diff.py and refreshed its callers",
            ),
            width,
            label="tool done card",
        )
        assert len(rows) == 1, rows
        assert "edit" in rows[0], rows[0]


def _c_test_tool_start_card_never_wraps_at_any_width(monkeypatch) -> None:
    """A start card with a cue, tag, detail and `executing` stays one row."""
    for width in WIDTHS:
        _at_width(monkeypatch, width)
        rows = _assert_fits(
            lambda: render_tool_card_start(
                ToolCard(tool="bash", detail="pytest -q tests/test_ui_ux.py --maxfail=1 -x"),
                running=True,
            ),
            width,
            label="tool start card",
        )
        assert len(rows) == 1, rows
        # What the reader is waiting for must survive every width.
        assert "executing" in rows[0], rows[0]


def _c_test_bash_block_marker_and_rows_never_wrap(monkeypatch) -> None:
    """Command rows and the overflow marker are clipped, not left to wrap."""
    command = "\n".join(
        "pytest -q tests/test_ui_ux.py::test_bash_block_marker_and_rows_never_wrap --maxfail=1"
        for _ in range(12)
    )
    for width in WIDTHS:
        _at_width(monkeypatch, width)
        rows = _assert_fits(
            lambda: render_bash_command_block(command), width, label="bash block"
        )
        assert any("+7 lines" in row for row in rows), rows
        assert any("/last" in row for row in rows), rows


def _c_test_code_edit_preview_never_wraps_and_keeps_its_stat(monkeypatch) -> None:
    """A long path and long content rows stay inside the window; the stat is metadata."""
    args = {
        "path": "src/kite/ui/" + "deeply_nested/" * 6 + "target_module.py",
        "old_string": "\n".join(f"old line {i} with padding to force a clip" for i in range(20)),
        "new_string": "\n".join(f"new line {i} with padding to force a clip" for i in range(20)),
    }
    for width in WIDTHS:
        _at_width(monkeypatch, width)
        rows = _assert_fits(
            lambda: render_code_edit_preview("edit", args), width, label="edit preview"
        )
        # The path and the diff stat are the header; both always print.
        assert "target_module" in rows[0], rows[0]
        assert "+20,-20" in rows[0], rows[0]
        assert any("+35 lines" in row and "/last" in row for row in rows), rows


def _c_test_status_line_never_wraps_at_any_width(monkeypatch) -> None:
    """Segment soup stays on one row: the footer dropping the least-useful bits."""
    for width in WIDTHS:
        _at_width(monkeypatch, width)
        rows = _assert_fits(lambda: render_status(_busy_state()), width, label="status line")
        assert len(rows) == 1, rows
        # The brand plus the fields a reader scans for must survive 60 cols.
        assert "kite" in rows[0] and "build" in rows[0] and "$0.123" in rows[0], rows[0]


def _c_test_narrow_buys_room_by_dropping_the_bar_not_the_count_or_the_item(monkeypatch) -> None:
    """The in-flight item and the count are the content; the bar is decoration."""
    items = _overflow(_items())
    _at_width(monkeypatch, 120)
    wide = _assert_fits(lambda: render_plan_tasks(items), 120, label="compact task line")[0]
    assert "1/3" in wide, wide
    assert "make the tool card overflow markers con" in wide, wide
    assert glyph("bar_fill") in wide, wide

    _at_width(monkeypatch, 60)
    narrow = _assert_fits(lambda: render_plan_tasks(items), 60, label="compact task line")[0]
    # The count and the item in flight are never what gets cut.
    assert "1/3" in narrow, narrow
    assert "make the tool card overflow" in narrow, narrow
    # The bar is what goes.
    assert glyph("bar_fill") not in narrow, narrow
    # The clip is honest about what it dropped.
    assert narrow.endswith("…"), narrow


def _c_test_a_done_family_tag_is_not_repeated_next_to_the_tool_name(monkeypatch) -> None:
    """`edit · edit` was the same idea twice; the tag only adds information."""
    _at_width(monkeypatch, 120)
    start = render_tool_card_start(ToolCard(tool="edit"), running=False).plain
    done = render_tool_card_done("edit", ok=True).plain
    assert "edit · edit" not in start, start
    assert "edit edit" not in done, done
    # A tag that does differ from the tool name still shows.
    read_start = render_tool_card_start(ToolCard(tool="grep"), running=False).plain
    assert "grep · read" in read_start, read_start


def _c_test_status_line_drops_background_counts_before_the_scanned_fields(monkeypatch) -> None:
    """A crowded footer sheds jobs/agents before mode, model or cost.

    The long model id is what makes the row actually crowded: at 60 cols with
    only ``llama-3.3-70b`` the whole row already fits, so nothing has to go and
    dropping one would be a regression rather than a fix.
    """
    state = _busy_state()
    state.model = "some-really-long-model-identifier-v3"
    _at_width(monkeypatch, 120)
    wide = [text for text, _ in status_segments(state)]
    assert "1 job" in wide and "2 agents" in wide, wide

    _at_width(monkeypatch, 60)
    narrow = [text for text, _ in status_segments(state)]
    joined = " ".join(narrow)
    # Background-work counts are the ones worth losing.
    assert "job" not in joined, narrow
    assert "agent" not in joined, narrow
    # What a reader scans for is not.
    for kept in ("build", "$0.123"):
        assert kept in narrow, f"{kept} must survive a 60-col footer, got {narrow}"
    assert any("some-really-long-model" in text for text in narrow), narrow


def _c_test_a_status_error_outranks_cost_when_the_row_is_tight(monkeypatch) -> None:
    """Error state is a field the user scans for, so it beats the cost figure."""
    state = _busy_state()
    state.busy = False
    state.last_error = "step or cost budget reached " + "x" * 90
    _at_width(monkeypatch, 60)
    rows = _assert_fits(lambda: render_status(state), 60, label="status line with error")
    assert any("err " in row for row in rows), rows


def _c_test_status_tail_and_rich_footer_agree_on_one_row(monkeypatch) -> None:
    """The toolbar tail and the Rich footer share one width budget and one join."""
    state = _busy_state()
    for width in WIDTHS:
        _at_width(monkeypatch, width)
        tail = format_status_tail(state)
        rows = _assert_fits(lambda: render_status(state), width, label="status line")
        assert cell_len(tail) <= width, f"status tail {width}: {tail!r}"
        # Every segment the footer shows, the tail carries — no two truths.
        for text, _style in status_segments(state):
            assert text in tail and text in rows[0], (text, tail, rows[0])


def _c_test_detail_view_keeps_every_context_bit_the_footer_drops(monkeypatch) -> None:
    """/status is the place to see the bits a narrow footer sheds, so it keeps them."""
    state = _busy_state()
    _at_width(monkeypatch, 60)
    narrow = [text for text, _ in status_segments(state)]
    from kite.ui.status import status_detail_lines

    detail = "\n".join(status_detail_lines(state))
    # Every context bit the footer sheds is still in /status — one per line.
    assert "jobs 1" in detail, detail
    assert "working" in detail, detail
    assert "1 task" in detail, detail
    assert "jobs 1" not in " ".join(narrow), narrow
    assert "working" not in narrow, narrow


def _c_test_overflow_markers_say_the_same_thing_for_write_edit_and_bash() -> None:
    """One phrasing across every surface that cuts a body."""
    write = render_code_edit_preview(
        "write", {"path": "a.py", "content": "\n".join(f"line {i}" for i in range(20))}
    )
    edit = render_code_edit_preview(
        "edit",
        {
            "path": "a.py",
            "old_string": "\n".join(f"old {i}" for i in range(20)),
            "new_string": "\n".join(f"new {i}" for i in range(20)),
        },
    )
    bash = render_bash_command_block("\n".join(f"echo {i}" for i in range(20)))
    assert write is not None and edit is not None

    markers = []
    for block in (write, edit, bash):
        rows = [ln for ln in block.plain.splitlines() if "/last" in ln]
        assert len(rows) == 1, f"expected one marker row, got {rows}"
        markers.append(rows[0].strip())
    # Identical glyph, separator and phrasing — only the count differs, and each
    # count matches what that surface actually hid. write and bash both hide 15
    # rows of the same 20-line body, so they read identically on purpose.
    assert markers[0] == markers[2], markers
    assert re.fullmatch(r"\u250a \u2026 \+\d+ lines  /last", markers[1]), markers[1]
    assert "+15 lines" in markers[0] and "+35 lines" in markers[1]
    # And each is the shared builder, not three literals that happen to match.
    assert markers[0].endswith(overflow_marker(15))
    assert markers[1].endswith(overflow_marker(35))
    assert markers[2].endswith(overflow_marker(15))


def _c_test_overflow_marker_names_a_command_that_exists_and_never_expand() -> None:
    """/last re-prints the record; /expand only reshapes future calls."""
    from kite.ui import commands as commands_mod
    from kite.ui.commands import BUILTINS

    registered = frozenset(b.name for b in BUILTINS) | frozenset(commands_mod.ALIASES)
    marker = overflow_marker(35)
    assert marker == "… +35 lines  /last"
    assert "last" in registered
    # /expand cannot bring back rows that already scrolled past.
    assert "expand" not in marker


def _c_test_preview_budget_is_still_five_and_narrow_never_buys_more_rows(monkeypatch) -> None:
    """The v1.0.6 density change stands: 5 body rows, at every width."""
    assert PREVIEW_LINES == 5
    content = "\n".join(f"line {i:02d}" for i in range(30))

    for width in WIDTHS:
        _at_width(monkeypatch, width)
        edit = render_code_edit_preview("write", {"path": "a.py", "content": content})
        assert edit is not None
        rows = [ln for ln in edit.plain.splitlines() if "line " in ln and "/last" not in ln]
        assert len(rows) == PREVIEW_LINES, f"width {width}: {rows}"

        bash = render_bash_command_block(content)
        rows = [ln for ln in bash.plain.splitlines() if "line " in ln and "/last" not in ln]
        assert len(rows) == PREVIEW_LINES, f"width {width}: {rows}"

    # The scroll path through RunDisplay is capped the same way.
    display, buf = _display()
    display.state.expanded_all = False
    display(Event("tool_end", payload={"tool": "bash", "ok": True, "output": content}))
    display.close()
    body = [ln for ln in strip_ansi(buf.getvalue()).splitlines() if "line " in ln]
    assert len(body) == PREVIEW_LINES, body


def _c_test_separators_and_glyphs_match_across_the_surfaces_i_normalised() -> None:
    """One separator mark everywhere, one gutter, on every row type."""
    sep = glyph("sep")
    items = _overflow(_items())
    header = render_plan_tasks(items).plain
    assert f"  {sep} " in header, header
    assert header.startswith("  "), header
    # The item separator, not the between-fields form the tool cards use.
    assert f" {sep} " not in header.replace(f"  {sep} ", ""), header

    start = render_tool_card_start(ToolCard(tool="bash", detail="pytest"), running=True).plain
    done = render_tool_card_done("bash", ok=True, meta="4ms").plain
    assert f" {sep} " in start and f" {sep} " in done, (start, done)
    # The doubled separator a f-string could produce is gone.
    assert f"{sep}  {sep}" not in start and f"{sep}  {sep}" not in done
    assert not start.endswith(sep) and not done.endswith(sep), (start, done)

    batch = render_parallel_batch_header(3, ["read", "bash"]).plain
    # The trailing inline item takes the house item separator — two spaces
    # before the mark, one after — not the between-fields single-space form.
    assert f"  {sep} " in batch, batch
    assert f" tools {sep} " not in batch, batch

    summary = render_tool_summary(preview="a long summary that will be clipped at narrow widths").plain
    assert summary.startswith("    "), summary
    meter_bits = render_parallel_batch_header(1).plain
    assert meter_bits.startswith("  "), meter_bits


def _c_test_clipped_paths_always_still_identify_the_file() -> None:
    """A clipped path must name its file — never degrade to a bare ellipsis.

    The failure this guards: a path with no ``/`` in it (a bare filename) walked
    its single segment, failed the fit test, and returned ``…`` — which is a row
    that says nothing about which file was touched. The ladder is: keep whole
    leading directories out first, then cut into the last segment from the front.
    """
    from kite.ui.tool_cards import _clip_path

    cases = [
        # (path, limit, must still contain)
        ("target_module.py", 17, "target_module.py"),
        ("target_module.py", 16, "target_module.py"),
        ("target_module.py", 10, "module.py"),
        ("target_module.py", 5, "e.py"),
        ("src/app.py", 8, "app.py"),
        ("src/kite/ui/deep/target_module.py", 20, "target_module.py"),
        ("src/kite/ui/deep/target_module.py", 12, "t_module.py"),
    ]
    for path, limit, must in cases:
        out = _clip_path(path, limit)
        assert cell_len(out) <= limit, (path, limit, out)
        assert must in out, f"{path!r} at {limit} cols lost its file: {out!r}"
        assert out != "\u2026", f"{path!r} at {limit} cols degraded to a bare ellipsis"

    # Windows separators are normalised the same way.
    assert "app.py" in _clip_path(r"src\\kite\\app.py", 12)

    # Degrading all the way: an empty path stays empty, and only a limit too
    # small for an ellipsis plus one character yields a bare ellipsis.
    assert _clip_path("", 10) == ""
    assert _clip_path("a.py", 1) == "\u2026"
    assert cell_len(_clip_path("a.py", 2)) <= 2


def _c_test_a_clipped_value_keeps_the_identifying_end_when_it_is_a_filename() -> None:
    """`_clip_tail` exists because prose clips from the right and names lose meaning."""
    from kite.ui.tool_cards import _clip_tail

    assert _clip_tail("target_module.py", 10) == "\u2026module.py"
    assert _clip_tail("abcdefghijkl", 5) == "\u2026ijkl"
    assert _clip_tail("short", 40) == "short"
    for text, limit in [("x" * 50, n) for n in range(1, 12)]:
        assert cell_len(_clip_tail(text, limit)) <= max(limit, 1)


def _c_test_task_row_badge_rides_the_right_edge_without_wrapping(monkeypatch) -> None:
    """The itemized row clips its content so the status badge is never pushed off."""
    long_item = TodoItem(id="9", content="word " * 60, status="in_progress")
    for width in WIDTHS:
        _at_width(monkeypatch, width)
        rows = _assert_fits(lambda: render_task_row(long_item), width, label="task row")
        assert len(rows) == 1, rows
        assert rows[0].rstrip().endswith("In progress"), rows[0]


def _c_test_run_meter_and_summary_stay_one_row_when_narrow(monkeypatch) -> None:
    """The trailing footer rows are one-liners by contract; narrow drops, never wraps."""
    from kite.ui.tool_cards import render_run_meter

    for width in WIDTHS:
        _at_width(monkeypatch, width)
        assert _assert_fits(
            lambda: render_run_meter(
                tools=128, duration_ms=4210, tokens=1_234_567, cost=12.3456, n_calls=9
            ),
            width,
            label="run meter",
        )
        _assert_fits(
            lambda: render_tool_summary(preview="summary text " * 30, line_count=999),
            width,
            label="tool summary",
        )


def _c_test_ascii_font_pack_keeps_every_normalised_row_one_line(monkeypatch) -> None:
    """Normalising on glyph('sep') means the ascii pack swaps with everything else."""
    from kite.ui.theme import reset_prefs

    reset_prefs(theme="auto", font="ascii")
    try:
        assert glyph("sep") == "|", glyph("sep")
        items = _overflow(_items())
        for width in WIDTHS:
            _at_width(monkeypatch, width)
            header = _assert_fits(lambda: render_plan_tasks(items), width, label="task line (ascii)")
            assert "|" in header[0], header
            _assert_fits(
                lambda: render_tool_card_start(ToolCard(tool="bash", detail="pytest -q x"), running=True),
                width,
                label="start card (ascii)",
            )
            _assert_fits(lambda: render_status(_busy_state()), width, label="status line (ascii)")
    finally:
        reset_prefs(theme="auto", font="unicode")


def test_batch_00(monkeypatch) -> None:
    """Consolidated (bodies unchanged): never-wraps."""
    _c_test_compact_task_line_never_wraps_at_any_width(monkeypatch=monkeypatch)
    _c_test_tool_done_card_never_wraps_at_any_width(monkeypatch=monkeypatch)
    _c_test_tool_start_card_never_wraps_at_any_width(monkeypatch=monkeypatch)
    _c_test_bash_block_marker_and_rows_never_wrap(monkeypatch=monkeypatch)
    _c_test_code_edit_preview_never_wraps_and_keeps_its_stat(monkeypatch=monkeypatch)
    _c_test_status_line_never_wraps_at_any_width(monkeypatch=monkeypatch)


def test_batch_01(monkeypatch) -> None:
    """Consolidated (bodies unchanged): narrow-sheds-decoration."""
    _c_test_narrow_buys_room_by_dropping_the_bar_not_the_count_or_the_item(monkeypatch=monkeypatch)
    _c_test_a_done_family_tag_is_not_repeated_next_to_the_tool_name(monkeypatch=monkeypatch)
    _c_test_status_line_drops_background_counts_before_the_scanned_fields(monkeypatch=monkeypatch)
    _c_test_a_status_error_outranks_cost_when_the_row_is_tight(monkeypatch=monkeypatch)
    _c_test_status_tail_and_rich_footer_agree_on_one_row(monkeypatch=monkeypatch)
    _c_test_detail_view_keeps_every_context_bit_the_footer_drops(monkeypatch=monkeypatch)


def test_batch_02(monkeypatch) -> None:
    """Consolidated (bodies unchanged): overflow+preview-budget."""
    _c_test_overflow_markers_say_the_same_thing_for_write_edit_and_bash()
    _c_test_overflow_marker_names_a_command_that_exists_and_never_expand()
    _c_test_preview_budget_is_still_five_and_narrow_never_buys_more_rows(monkeypatch=monkeypatch)


def test_batch_03(monkeypatch) -> None:
    """Consolidated (bodies unchanged): separators+clip+task-row+meter."""
    _c_test_separators_and_glyphs_match_across_the_surfaces_i_normalised()
    _c_test_clipped_paths_always_still_identify_the_file()
    _c_test_a_clipped_value_keeps_the_identifying_end_when_it_is_a_filename()
    _c_test_task_row_badge_rides_the_right_edge_without_wrapping(monkeypatch=monkeypatch)
    _c_test_run_meter_and_summary_stay_one_row_when_narrow(monkeypatch=monkeypatch)
    _c_test_ascii_font_pack_keeps_every_normalised_row_one_line(monkeypatch=monkeypatch)