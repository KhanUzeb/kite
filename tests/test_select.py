"""Interactive model/provider picker."""

from __future__ import annotations

from unittest.mock import MagicMock

from kite.providers.select import _can_use_radiolist, _numbered_pick, select_model_interactive


def test_can_use_radiolist_false_on_windows(monkeypatch) -> None:
    monkeypatch.setattr("kite.providers.select.sys.platform", "win32")
    assert _can_use_radiolist() is False


def test_numbered_pick_by_index() -> None:
    console = MagicMock()
    console.input.return_value = "2"
    chosen = _numbered_pick(
        console,
        [("a", "alpha"), ("b", "beta"), ("c", "gamma")],
        current="a",
        title="t",
        noun="model",
    )
    assert chosen == "b"


def test_select_model_byos_unlinked_asks_login(kite_home, monkeypatch) -> None:
    monkeypatch.setattr("kite.providers.select._can_use_radiolist", lambda: False)
    console = MagicMock()
    code, provider, model = select_model_interactive(console, "chatgpt")
    assert code == 1
    assert provider is None
    assert "kite login chatgpt" in " ".join(str(c) for c in console.print.call_args_list)


def test_select_model_byos_linked_picks_live(kite_home, monkeypatch) -> None:
    monkeypatch.setattr("kite.providers.select._can_use_radiolist", lambda: False)
    monkeypatch.setattr("kite.providers.byos.has_oauth_session", lambda _p: True)
    monkeypatch.setattr(
        "kite.providers.byos.fetch_oauth_model_ids",
        lambda spec, refresh=False: ("gpt-5.6-luna", "gpt-5.4"),
    )
    console = MagicMock()
    console.input.return_value = "2"
    code, provider, model = select_model_interactive(console, "chatgpt", persist=False)
    assert code == 0
    assert provider == "chatgpt"
    assert model == "gpt-5.4"
