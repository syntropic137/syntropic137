"""Shared scanning for the syn-ui data-layer fitness functions (ADR-074).

TypeScript and Svelte sources are read as text. Comments are blanked before
matching, so prose that mentions ``fetch(`` or a package name never counts;
string literals are kept, because a URL in a string is exactly what the checks
look for.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SYN_UI_APP = ROOT / "apps" / "syn-ui"
SYN_UI_PACKAGES = ROOT / "packages" / "syn-ui"
DATA = SYN_UI_PACKAGES / "data"

#: Source files the checks read.
SOURCE_SUFFIXES = frozenset({".ts", ".js", ".mjs", ".svelte"})
#: Build output and installed packages are never first-party source.
SKIP_DIRS = frozenset({"node_modules", "dist", ".dist", ".results", ".report", ".svelte-kit"})

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->", re.DOTALL)
#: A `//` comment, but not the `//` inside `http://` or a string like '//'.
_LINE_COMMENT = re.compile(r"(?<![:'\"`\\])//[^\n]*")


def strip_comments(text: str) -> str:
    """Blank comments, keeping line numbers stable."""

    def blank(m: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    return _LINE_COMMENT.sub(blank, _BLOCK_COMMENT.sub(blank, text))


def source_files(root: Path) -> list[Path]:
    """Every TS/JS/Svelte file under ``root``, skipping build output and dependencies."""
    if not root.exists():
        return []
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix in SOURCE_SUFFIXES
        and not SKIP_DIRS.intersection(p.relative_to(root).parts)
    )


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1
