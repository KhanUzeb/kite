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


def test_numbered_pick_cancel_empty() -> None:
    console = MagicMock()
    console.input.return_value = ""
    assert (
        _numbered_pick(console, [("a", "alpha")], current=None, title="t", noun="model")
        is None
    )


def test_numbered_pick_refresh() -> None:
    from kite.ui.pick import REFRESH_PICK, numbered_pick

    console = MagicMock()
    console.input.return_value = "r"
    chosen = numbered_pick(
        console,
        [("a", "alpha"), ("b", "beta")],
        current=None,
        title="t",
        noun="model",
        refreshable=True,
    )
    assert chosen == REFRESH_PICK


def test_clear_model_list_cache() -> None:
    import importlib

    lm = importlib.import_module("kite.providers.list_models")
    lm._LIST_CACHE["groq"] = (0.0, MagicMock())
    lm.clear_model_list_cache("groq")
    assert "groq" not in lm._LIST_CACHE
    lm._LIST_CACHE["a"] = (0.0, MagicMock())
    lm.clear_model_list_cache()
    assert lm._LIST_CACHE == {}


def test_numbered_pick_by_id() -> None:
    console = MagicMock()
    console.input.return_value = "gamma"
    chosen = _numbered_pick(
        console,
        [("a", "alpha"), ("b", "beta"), ("c", "gamma")],
        current=None,
        title="t",
        noun="model",
    )
    assert chosen == "c"


def test_select_model_byos_unlinked_asks_login(kite_home, monkeypatch) -> None:
    monkeypatch.setattr("kite.providers.select._can_use_radiolist", lambda: False)
    console = MagicMock()
    code, provider, model = select_model_interactive(console, "chatgpt")
    assert code == 1
    assert provider is None
    assert model is None
    printed = " ".join(str(c) for c in console.print.call_args_list)
    assert "kite login chatgpt" in printed


def test_select_model_byos_linked_picks_live(kite_home, monkeypatch) -> None:
    from kite.providers.byos import oauth_auth_file

    auth = oauth_auth_file("chatgpt")
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text('{"access_token": "t"}', encoding="utf-8")
    monkeypatch.setattr("kite.providers.select._can_use_radiolist", lambda: False)
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


def test_render_pick_list_numbers() -> None:
    from kite.ui.credentials import render_pick_list

    text = str(render_pick_list([("groq", "Groq"), ("chatgpt", "ChatGPT")], title="Select a provider"))
    assert "Select a provider" in text
    assert "1" in text
    assert "Groq" in text


def test_connect_interactive_logs_in_then_picks(kite_home, monkeypatch) -> None:
    from kite.providers.byos import oauth_auth_file
    from kite.providers.select import connect_interactive

    auth = oauth_auth_file("chatgpt")
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text('{"access_token": "t"}', encoding="utf-8")
    monkeypatch.setattr("kite.providers.select._can_use_radiolist", lambda: False)
    monkeypatch.setattr(
        "kite.providers.credentials.login_provider",
        lambda provider, set_default=True, console=None: (0, "linked", provider),
    )
    monkeypatch.setattr(
        "kite.providers.byos.fetch_oauth_model_ids",
        lambda spec, refresh=False: ("gpt-5.6-luna", "gpt-5.4"),
    )
    console = MagicMock()
    console.input.return_value = "1"
    code, provider, model = connect_interactive(
        console, provider="chatgpt", persist=False, force_login=True
    )
    assert code == 0
    assert provider == "chatgpt"
    assert model == "gpt-5.6-luna"
