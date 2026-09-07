"""Tool argument repair tests."""

from __future__ import annotations

from kite.models.tool_args import repair_tool_arguments


def test_repair_valid_json() -> None:
    args, err = repair_tool_arguments('{"path": "a.py"}')
    assert err is None
    assert args == {"path": "a.py"}


def test_repair_fenced_json() -> None:
    raw = '```json\n{"command": "ls"}\n```'
    args, err = repair_tool_arguments(raw)
    assert err is None
    assert args == {"command": "ls"}


def test_repair_trailing_comma() -> None:
    args, err = repair_tool_arguments('{"a": 1,}')
    assert err is None
    assert args == {"a": 1}


def test_repair_fails_on_garbage() -> None:
    args, err = repair_tool_arguments("not json at all {{{")
    assert args is None
    assert err
