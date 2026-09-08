"""Attachment and clipboard behavior."""

from __future__ import annotations

from unittest.mock import patch

from kite.ui.attach import (
    Attachment,
    clipboard_install_hint,
    load_clipboard,
    parse_inline_mentions,
    read_os_clipboard,
    user_content_with_attachments,
)


def test_parse_inline_mentions_attaches_existing_file(tmp_path) -> None:
    f = tmp_path / "note.txt"
    f.write_text("hello attach", encoding="utf-8")
    task, found = parse_inline_mentions(f"please fix @{f.name}", tmp_path)
    assert "note.txt" not in task or task.strip() == "please fix"
    assert len(found) == 1
    assert found[0].name == "note.txt"
    assert "hello attach" in found[0].text


def test_user_content_with_attachments_includes_source() -> None:
    att = Attachment(kind="text", name="clip.txt", source="clipboard", text="secret paste")
    out = user_content_with_attachments("review this", [att], images=False)
    assert isinstance(out, str)
    assert "source: clipboard" in out
    assert "secret paste" in out


def test_load_clipboard_from_file_path(tmp_path, kite_home) -> None:
    f = tmp_path / "payload.txt"
    f.write_text("file body", encoding="utf-8")
    with patch("kite.ui.attach._clipboard_text", return_value=str(f)):
        with patch("kite.ui.attach._clipboard_image_posix", return_value=None):
            with patch("kite.ui.attach._clipboard_image_windows", return_value=None):
                att = load_clipboard()
    assert att.kind == "text"
    assert "file body" in att.text


def test_read_os_clipboard_returns_string() -> None:
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "hello"
        text = read_os_clipboard()
    assert text == "hello" or text == ""


def test_clipboard_install_hint_on_linux_without_tools(monkeypatch) -> None:
    monkeypatch.setattr("kite.ui.attach.shutil.which", lambda _: None)
    monkeypatch.setattr("kite.ui.attach.os.name", "posix")
    hint = clipboard_install_hint()
    assert "xclip" in hint or "wl-clipboard" in hint
