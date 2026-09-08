"""User-initiated attachments: files, clipboard, images.

These are read by Kite into the next user turn. They do not go through the
agent sandbox — the human is attaching from their own machine.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kite.config import ensure_home, kite_home

Kind = Literal["image", "text", "binary"]

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"})
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 80_000
MAX_ATTACHMENTS = 8
AT_RE = re.compile(r'(?:^|(?<=\s))@("([^"]+)"|(\S+))')


@dataclass
class Attachment:
    kind: Kind
    name: str
    source: str  # file | clipboard | @
    path: str = ""
    text: str = ""
    data: bytes = b""
    mime: str = ""

    def label(self) -> str:
        return f"{self.source}  {self.name}"


def attachments_dir() -> Path:
    ensure_home()
    path = kite_home() / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _mime_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }.get(ext, "application/octet-stream")


def load_file(path: str | Path, *, source: str = "file", cwd: str | Path | None = None) -> Attachment:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(cwd or Path.cwd()) / p
    p = p.resolve()
    if not p.is_file():
        raise FileNotFoundError(f"not a file: {p}")
    size = p.stat().st_size
    mime = _mime_for(p)
    name = p.name
    if p.suffix.lower() in IMAGE_EXTS or mime.startswith("image/"):
        if size > MAX_IMAGE_BYTES:
            raise ValueError(f"image too large ({size} bytes, max {MAX_IMAGE_BYTES})")
        data = p.read_bytes()
        return Attachment(kind="image", name=name, source=source, path=str(p), data=data, mime=mime)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise ValueError(f"cannot read {p}: {e}") from e
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n...[truncated]..."
    return Attachment(kind="text", name=name, source=source, path=str(p), text=text, mime="text/plain")


def read_os_clipboard() -> str:
    """Read plain text from the OS clipboard (composer paste + /clip)."""
    try:
        import sys

        if sys.platform == "win32":
            import ctypes

            CF_UNICODETEXT = 13
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.OpenClipboard(0)
            try:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return ""
                ptr = kernel32.GlobalLock(handle)
                try:
                    return ctypes.wstring_at(ptr) if ptr else ""
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
    except Exception:
        pass
    for cmd in (
        ["pbpaste"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["wl-paste", "-n"],
    ):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
            )
            if proc.returncode == 0:
                return (proc.stdout or "").strip()
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue
    return ""


def write_os_clipboard(text: str) -> None:
    """Write plain text to the OS clipboard."""
    try:
        import sys

        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            encoded = text.encode("utf-16-le") + b"\x00\x00"
            user32.OpenClipboard(0)
            try:
                user32.EmptyClipboard()
                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
                ptr = kernel32.GlobalLock(handle)
                ctypes.memmove(ptr, encoded, len(encoded))
                kernel32.GlobalUnlock(handle)
                user32.SetClipboardData(CF_UNICODETEXT, handle)
            finally:
                user32.CloseClipboard()
            return
    except Exception:
        pass
    for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"], ["wl-copy"]):
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=3)
            return
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue


def clipboard_install_hint() -> str:
    if os.name == "nt":
        return ""
    if shutil.which("pbpaste") or shutil.which("wl-paste") or shutil.which("xclip"):
        return ""
    return "install pbpaste (macOS), wl-clipboard (Wayland), or xclip (X11) for clipboard support"


def _clipboard_text() -> str:
    if os.name == "nt":
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        text = (proc.stdout or "").strip()
        if text:
            return text
    return read_os_clipboard()


def _save_clipboard_image(data: bytes, dest: Path) -> Path | None:
    if len(data) < 32:
        return None
    dest.write_bytes(data)
    return dest if dest.is_file() else None


def _clipboard_image_windows() -> Path | None:
    dest = attachments_dir() / f"clip-{int(time.time())}.png"
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$img = [System.Windows.Forms.Clipboard]::GetImage(); "
        "if ($null -eq $img) { exit 2 }; "
        f"$img.Save('{str(dest).replace(chr(39), chr(39)+chr(39))}', [System.Drawing.Imaging.ImageFormat]::Png);"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 32:
        return dest
    return None


def _clipboard_image_posix() -> Path | None:
    dest = attachments_dir() / f"clip-{int(time.time())}.png"
    if shutil.which("pngpaste"):
        try:
            proc = subprocess.run(["pngpaste", str(dest)], capture_output=True, timeout=8)
            if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 32:
                return dest
        except (OSError, subprocess.TimeoutExpired):
            pass
    if shutil.which("wl-paste"):
        try:
            proc = subprocess.run(
                ["wl-paste", "-t", "image/png"],
                capture_output=True,
                timeout=8,
            )
            if proc.returncode == 0 and proc.stdout:
                return _save_clipboard_image(proc.stdout, dest)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if shutil.which("xclip"):
        try:
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                capture_output=True,
                timeout=8,
            )
            if proc.returncode == 0 and proc.stdout:
                return _save_clipboard_image(proc.stdout, dest)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def load_clipboard() -> Attachment:
    if os.name == "nt":
        image = _clipboard_image_windows()
        if image is not None:
            return load_file(image, source="clipboard")
    else:
        image = _clipboard_image_posix()
        if image is not None:
            return load_file(image, source="clipboard")
    text = _clipboard_text()
    if not text:
        hint = clipboard_install_hint()
        extra = f" ({hint})" if hint else ""
        raise ValueError(f"clipboard is empty{extra}")
    # If clipboard holds a path to an existing file, attach that file.
    maybe = Path(text.strip().strip('"')).expanduser()
    if maybe.is_file():
        return load_file(maybe, source="clipboard")
    name = f"clipboard-{int(time.time())}.txt"
    dump = attachments_dir() / name
    dump.write_text(text, encoding="utf-8")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n...[truncated]..."
    return Attachment(kind="text", name=name, source="clipboard", path=str(dump), text=text, mime="text/plain")


def parse_inline_mentions(task: str, cwd: str | Path) -> tuple[str, list[Attachment]]:
    """Pull @path tokens that exist on disk into attachments; leave the rest."""
    found: list[Attachment] = []
    root = Path(cwd).expanduser().resolve()

    def consume(match: re.Match[str]) -> str:
        raw = (match.group(2) or match.group(3) or "").strip()
        if not raw or raw.startswith(("http://", "https://")):
            return match.group(0)
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = root / raw
        if not candidate.is_file():
            return match.group(0)
        if len(found) >= MAX_ATTACHMENTS:
            return match.group(0)
        try:
            found.append(load_file(candidate, source="@", cwd=root))
        except (OSError, ValueError):
            return match.group(0)
        return " "

    leftover = AT_RE.sub(consume, task)
    leftover = re.sub(r"[ \t]{2,}", " ", leftover).strip()
    return leftover, found


def collect_turn_attachments(task: str, cwd: str | Path, pending: list[Attachment]) -> tuple[str, list[Attachment]]:
    leftover, mentioned = parse_inline_mentions(task, cwd)
    out = list(pending) + mentioned
    if len(out) > MAX_ATTACHMENTS:
        raise ValueError(f"too many attachments (max {MAX_ATTACHMENTS})")
    return leftover, out


def image_data_url(att: Attachment) -> str:
    b64 = base64.b64encode(att.data).decode("ascii")
    mime = att.mime or "image/png"
    return f"data:{mime};base64,{b64}"


def user_content_with_attachments(text: str, attachments: list[Attachment], *, images: bool = True) -> str | list[dict[str, Any]]:
    """OpenAI-style content list when images are included; otherwise a string."""
    parts: list[dict[str, Any]] = []
    blocks: list[str] = [text.rstrip()]
    image_atts = [a for a in attachments if a.kind == "image"]
    text_atts = [a for a in attachments if a.kind != "image"]
    for att in text_atts:
        body = att.text or ""
        source = att.source or "file"
        blocks.append(f"\n\n# Attached {att.name} (source: {source})\n```\n{body}\n```")
    if not images:
        for att in image_atts:
            blocks.append(f"\n\n# Image attached (not sent — no vision model): {att.name}")
        return "\n".join(blocks).strip() + "\n"
    prompt = "\n".join(blocks).strip()
    if not image_atts:
        return prompt + ("\n" if prompt else "")
    parts.append({"type": "text", "text": prompt})
    for att in image_atts:
        parts.append({"type": "image_url", "image_url": {"url": image_data_url(att)}})
    return parts


def strip_media_for_summary(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    bits: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            bits.append(str(part.get("text") or ""))
        elif part.get("type") == "image_url":
            bits.append("[image]")
    return " ".join(bits)
