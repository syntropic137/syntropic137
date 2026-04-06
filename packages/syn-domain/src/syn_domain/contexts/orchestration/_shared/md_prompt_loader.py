"""Markdown prompt file loader for workflow phases.

Parses .md files using the Claude Code command format:
optional YAML frontmatter between --- delimiters, followed by markdown body.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MdPrompt:
    """Result of loading a .md prompt file.

    Attributes:
        content: The markdown body (everything after frontmatter).
        metadata: Parsed frontmatter key-value pairs (empty dict if no frontmatter).
    """

    content: str
    metadata: dict[str, Any]


_FRONTMATTER_DELIMITER = "---"

# Frontmatter keys that map to PhaseYamlDefinition fields (kebab → snake).
_KEBAB_TO_SNAKE: dict[str, str] = {
    "argument-hint": "argument_hint",
    "allowed-tools": "allowed_tools",
    "execution-type": "execution_type",
    "max-tokens": "max_tokens",
    "timeout-seconds": "timeout_seconds",
}


def load_md_prompt(path: Path) -> MdPrompt:
    """Load a markdown prompt file, parsing optional YAML frontmatter.

    Args:
        path: Path to the .md file.

    Returns:
        MdPrompt with parsed content and metadata.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the frontmatter YAML is malformed.
    """
    if not path.is_file():
        msg = f"Prompt file not found: {path}"
        raise FileNotFoundError(msg)

    text = path.read_text(encoding="utf-8")
    return _parse_md_prompt(text, source_path=path)


def _parse_md_prompt(text: str, *, source_path: Path | None = None) -> MdPrompt:
    """Parse markdown text into frontmatter metadata and body content."""
    split = _split_frontmatter(text)
    if split is None:
        return MdPrompt(content=text.strip(), metadata={})

    frontmatter_raw, body = split
    metadata = _parse_frontmatter_yaml(frontmatter_raw, source_path)
    return MdPrompt(content=body.strip(), metadata=metadata)


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    """Split text into (frontmatter_raw, body) or None if no frontmatter.

    Delimiter lines must be exactly ``---`` (handles both LF and CRLF).
    Lines like ``---extra`` are NOT treated as delimiters.
    """
    lines = text.splitlines(keepends=True)

    # Skip leading blank lines.
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines):
        return None

    # Opening delimiter must be exactly '---'.
    if lines[idx].rstrip("\r\n") != _FRONTMATTER_DELIMITER:
        return None
    idx += 1

    # Find closing delimiter.
    close_idx: int | None = None
    for j in range(idx, len(lines)):
        if lines[j].rstrip("\r\n") == _FRONTMATTER_DELIMITER:
            close_idx = j
            break

    if close_idx is None:
        return None

    frontmatter_raw = "".join(lines[idx:close_idx])
    body = "".join(lines[close_idx + 1 :])
    return frontmatter_raw, body


def _parse_frontmatter_yaml(raw: str, source_path: Path | None) -> dict[str, Any]:
    """Parse frontmatter YAML string into a dict."""
    location = f" in {source_path}" if source_path else ""

    try:
        metadata = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        msg = f"Malformed YAML frontmatter{location}: {e}"
        raise ValueError(msg) from e

    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        msg = f"YAML frontmatter must be a mapping{location}, got {type(metadata).__name__}"
        raise ValueError(msg)

    return metadata


def normalize_frontmatter(metadata: dict[str, Any]) -> dict[str, Any]:
    """Convert frontmatter kebab-case keys to snake_case for PhaseYamlDefinition.

    Also normalizes ``allowed-tools`` from a comma-separated string to a list.
    """
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        snake_key = _KEBAB_TO_SNAKE.get(key, key)

        # Normalize allowed_tools: comma-separated string → list.
        if snake_key == "allowed_tools" and isinstance(value, str):
            value = [tool.strip() for tool in value.split(",") if tool.strip()]

        result[snake_key] = value

    return result
