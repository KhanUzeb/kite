"""Kite — slim hybrid coding-agent harness.

Layout
------
  agent/     loop, runtime, harness, mode, events, exceptions
  cli/       argparse entry, slash index
  ui/        Rich TUI
  config/    ~/.kite prefs + runtime TOML
  tools/ env/ models/ providers/ prompts/
  context/ memory/ guardrails/
  skills/ commands/ plugins/   # markdown extensions
  data/    packaged prompts, skills, catalog

Design lineage
--------------
* mini-swe-agent: Agent / Model / Environment split, linear message history,
  one-step = query + execute, subprocess-per-action, cost/step limits,
  trajectory dump, exception-driven exit.
* tau: typed tools, event stream, stateful harness, provider catalog,
  project context discovery, session memory, context accounting/compaction.
"""

__version__ = "0.6.1"
