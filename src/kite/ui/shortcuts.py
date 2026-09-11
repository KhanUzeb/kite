"""REPL keyboard shortcut reference — single source for help and docs."""

from __future__ import annotations

IDLE_SHORTCUTS = """\
composer (idle)
  Enter           send message
  Tab             cycle / and @file completions
  Ctrl+V          paste OS clipboard into composer
  F8 / Esc v      attach clipboard to next turn (/clip)
  Ctrl+Insert     copy composer selection to clipboard
  Shift+Insert    paste OS clipboard
  Ctrl+C          clear line (does not quit)
  Ctrl+D          quit REPL
  Ctrl+L          clear screen
  Ctrl+O / F6     toggle expanded tool output
  Ctrl+P / F3     plan mode
  Ctrl+B / F4     build mode
  Ctrl+T / F7     toggle thinking trace
  Ctrl+Space      toggle cockpit / compact layout
  F2              flash status footer
  F5              refresh models, then pick
  @path           attach file inline (e.g. fix @src/foo.py)
"""

BUSY_SHORTCUTS = """\
while a turn is running
  Enter           queue a follow-up
  Esc / Ctrl+C    stop the turn (session stays open)
  Ctrl+G          steer — stop and send composer text as next turn
  Ctrl+U          dequeue queued messages into composer
  F8 / Esc v      attach clipboard to next queued turn
  /tasks          running work + queue
  /live           stream bash output
  /live agents    stream subagent crew activity
"""

APPROVAL_SHORTCUTS = """\
approval prompt
  a / Enter       allow once (hotkeys only when composer is empty)
  s               allow this session
  p               allow always (when offered)
  n               deny
  q               stop run
  /approve …      change approval mode while a turn runs
"""


def shortcuts_help_text() -> str:
    return "\n".join(
        [
            "Keyboard shortcuts",
            "",
            IDLE_SHORTCUTS.strip(),
            "",
            BUSY_SHORTCUTS.strip(),
            "",
            APPROVAL_SHORTCUTS.strip(),
            "",
            "Attachments: /attach path · /clip · F8 · @file in composer · kite run --attach",
        ]
    )
