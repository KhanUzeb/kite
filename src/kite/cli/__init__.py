"""Process entry: argparse CLI, slash index, display adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])


@contextmanager
def _identity_argparse_gettext() -> Iterator[bool]:
    """Install an identity translator for one parser build, then restore it.

    Python 3.12 argparse binds ``gettext.gettext`` as its module-level ``_``;
    every help/error string then runs ``gettext.find()`` over locale directories
    even when no catalog exists. Kite ships no argparse translations. Rechecking
    on every use (and restoring afterwards) means a catalog or custom translator
    installed later is still honoured, and the stdlib is never left patched.
    """
    import argparse
    import gettext

    original = getattr(argparse, "_", None)
    if original is not gettext.gettext or gettext.find(gettext._current_domain):
        yield False
        return
    argparse._ = lambda message: message
    try:
        yield True
    finally:
        argparse._ = original


def fast_argparse_gettext(func: _F) -> _F:
    """Scope the argparse gettext fast path to a single function call."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with _identity_argparse_gettext():
            return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
