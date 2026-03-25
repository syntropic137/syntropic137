"""Environment file parser.

Extracted from op_resolver.py to reduce module complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _parse_line(line: str) -> tuple[str, str] | None:
    """Parse a single .env line into (key, value), or None if not a valid entry."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, _, raw_value = stripped.partition("=")
    key = key.strip()
    if not key:
        return None
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return key, value


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a key-value dict.

    Lines starting with ``#`` and blank lines are ignored.
    Values may be quoted with single or double quotes.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        parsed = _parse_line(raw_line)
        if parsed:
            result[parsed[0]] = parsed[1]
    return result
