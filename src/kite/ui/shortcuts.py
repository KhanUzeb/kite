"""REPL keyboard shortcut reference — single source for help and docs."""

from __future__ import annotations

IDLE_SHORTCUTS = """\
composer (idle)
  Enter           send message
  Alt+Enter / Ctrl+J  newline without sending (box grows to 7 rows, then scrolls)
  Tab             cycle / and @file completions
  ↑↓ / number / drag  CLI pickers — click or drag the mouse to highlight, release to select
  KITE_MOUSE=1        slash-menu wheel (off by default so the welcome banner stays readable)
  Ctrl+V          paste OS clipboard into composer
  F8 / Esc v      attach clipboard to next turn (/clip)
  Drag-select     copy transcript text (mouse stays with the terminal)
  Ctrl+Insert     copy composer selection to clipboard
  Shift+Insert    paste OS clipboard
  Ctrl+C          clear line (does not quit)
  Ctrl+D          quit REPL
  Ctrl+L          clear screen
  Ctrl+O / F6     toggle expanded tool output
  Ctrl+B / F4     build mode (default)
  Shift+Tab / Ctrl+P / F3  plan mode (opt-in read-only checklist)
  Ctrl+T / F7     toggle thinking trace
  F2              flash status footer
  F5              refresh models, then pick
  Ctrl+K          clear composer text
  Ctrl+R          search message history
  Ctrl+Y          cycle through history
  @path           attach file inline (e.g. fix @src/foo.py)
  !command        run a shell command and send output to the model (Pi)
  !!command       run a shell command without adding it to context
"""

BUSY_SHORTCUTS = """\
while a turn is running
  Enter           steer — stop and send composer text as next turn (default)
  Alt+Enter       queue a follow-up (KITE_BUSY_ENTER=queue swaps Enter/Alt+Enter)
  Esc / Ctrl+C    stop the turn (session stays open)
  Ctrl+G          steer (same as Enter)
  Ctrl+U          dequeue queued messages into composer
  Ctrl+K          clear composer text
  F8 / Esc v      attach clipboard to next queued turn
  /tasks          running work + queue
  /live           stream bash output
  /live agents    stream subagent crew activity
"""

APPROVAL_SHORTCUTS = """\
approval prompt
  Enter / a       allow this exact command (once)
  s               allow this command family for the session
  p               remember always (~/.kite/approvals.json)
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
