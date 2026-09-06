# kite-release-version: 0.9.1
"""Render docs/*.md to docs/*.pdf (fpdf2)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

SOURCES = [
    DOCS / "kite-system-design.md",
    DOCS / "cli-ux.md",
    DOCS / "ideal-cli-spec.md",
    ROOT / "kite_commands.md",
]


def _fonts() -> tuple[Path | None, Path | None, Path | None]:
    regular = bold = mono = None
    for path in (
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ):
        if path.is_file():
            regular = path
            break
    for path in (
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ):
        if path.is_file():
            bold = path
            break
    for path in (
        Path(r"C:\Windows\Fonts\consola.ttf"),
        Path(r"C:\Windows\Fonts\cour.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
        Path("/System/Library/Fonts/Supplemental/Courier New.ttf"),
    ):
        if path.is_file():
            mono = path
            break
    return regular, bold, mono


_SAFE = str.maketrans(
    {
        "✓": "+",
        "✗": "x",
        "⚠": "!",
        "●": "*",
        "○": "o",
        "▸": ">",
        "▾": "v",
        "›": ">",
        "•": ".",
        "…": "...",
        "↻": "~",
        "·": "|",
        "╭": "[",
        "╮": "]",
        "█": "#",
        "░": "-",
        "⊕": "+",
        "⚠": "!",
        "↻": "~",
        "\u26a0": "!",
        "\u21bb": "~",
        "\u2295": "+",
        "\u2713": "+",
    }
)


def _strip_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return text.replace("\t", "    ").translate(_SAFE)


def iter_blocks(md: str):
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            yield "pre", "\n".join(buf).translate(_SAFE)
            continue
        if line.strip().startswith("|") and "|" in line[1:]:
            buf = [line]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                buf.append(lines[i])
                i += 1
            rows = []
            for raw in buf:
                if re.match(r"^\s*\|?\s*:?-{3,}", raw):
                    continue
                cells = [c.strip() for c in raw.strip().strip("|").split("|")]
                rows.append("  |  ".join(_strip_inline(c) for c in cells))
            yield "pre", "\n".join(rows).translate(_SAFE)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            yield f"h{min(len(heading.group(1)), 4)}", _strip_inline(heading.group(2))
            i += 1
            continue
        if not line.strip() or line.strip() == "---":
            yield "gap", ""
            i += 1
            continue
        if re.match(r"^[-*]\s+", line) or re.match(r"^\d+\.\s+", line):
            buf = [line]
            i += 1
            while i < len(lines) and (
                re.match(r"^[-*]\s+", lines[i])
                or re.match(r"^\d+\.\s+", lines[i])
                or (lines[i].startswith("  ") and lines[i].strip())
            ):
                buf.append(lines[i])
                i += 1
            body = "\n".join(_strip_inline(x) for x in buf)
            yield "list", body
            continue
        yield "p", _strip_inline(line)
        i += 1


def build_one(src: Path, dest: Path) -> None:
    from fpdf import FPDF

    class Doc(FPDF):
        title_text = src.name

        def footer(self) -> None:
            self.set_y(-12)
            self.set_font(self.body_family, size=8)
            self.set_text_color(110, 110, 110)
            self.cell(0, 8, f"{self.title_text}  ·  {self.page_no()}/{{nb}}", align="C")
            self.set_text_color(0, 0, 0)

    pdf = Doc(format="Letter")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(16, 16, 16)
    pdf.add_page()
    regular, bold, mono = _fonts()
    family = "Helvetica"
    mono_family = "Courier"
    if regular:
        pdf.add_font("Kite", fname=str(regular))
        family = "Kite"
        if bold:
            pdf.add_font("Kite", style="B", fname=str(bold))
        else:
            pdf.add_font("Kite", style="B", fname=str(regular))
    if mono:
        pdf.add_font("KiteMono", fname=str(mono))
        mono_family = "KiteMono"
    pdf.body_family = family  # type: ignore[attr-defined]
    sizes = {"h1": 18, "h2": 14, "h3": 12, "h4": 11, "p": 10, "list": 10, "pre": 7.5}
    leading = {"h1": 9, "h2": 7, "h3": 6, "h4": 6, "p": 5, "list": 5, "pre": 3.6}

    for kind, text in iter_blocks(src.read_text(encoding="utf-8")):
        if kind == "gap":
            pdf.ln(3)
            continue
        if kind.startswith("h"):
            pdf.set_font(family, style="B", size=sizes[kind])
            pdf.multi_cell(0, leading[kind], text)
            pdf.ln(1.5)
            continue
        if kind == "pre":
            pdf.set_font(mono_family, size=sizes["pre"])
            pdf.set_fill_color(245, 245, 245)
            pdf.multi_cell(0, leading["pre"], text or " ", fill=True)
            pdf.ln(1)
            continue
        pdf.set_font(family, size=sizes[kind])
        pdf.multi_cell(0, leading[kind], text)
        pdf.ln(0.8)

    dest.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(dest))


def main() -> int:
    try:
        import fpdf  # noqa: F401
    except ImportError:
        print("install fpdf2:  uv pip install fpdf2", file=sys.stderr)
        return 1
    for src in SOURCES:
        if not src.is_file():
            continue
        dest = DOCS / f"{src.stem}.pdf"
        build_one(src, dest)
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
