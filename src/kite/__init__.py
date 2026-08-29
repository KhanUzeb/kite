"""Kite — slim hybrid coding-agent harness.

Design lineage
--------------
* mini-swe-agent: Agent / Model / Environment split, linear message history,
  one-step = query + execute, subprocess-per-action, cost/step limits,
  trajectory dump, exception-driven exit.
* tau: typed tools, event stream, stateful harness, provider catalog,
  project context discovery, session memory, context accounting/compaction.
"""

__version__ = "0.4.0"
