"""Workflow-author-facing reference to a Claude Code plugin (issue #726).

A ``ClaudePluginRef`` is what appears in workflow YAML under the
``claude_plugins:`` field at workflow- and phase-scope. It is the
*declared* reference (source + version), prior to any resolution
against the lock projection. Resolution turns a ``ClaudePluginRef``
into a ``ResolvedClaudePlugin`` (see ``value_objects.py``).

Three input forms are accepted (validator normalizes to one shape):

1. GitHub shorthand string ``"org/repo@version"``. The most common form.
2. Full URL string ``"<url>@<version>"``. For non-github sources.
3. Verbose mapping with ``source`` (or ``source_url``), ``version``, and
   optional explicit ``name`` override.

``@latest`` is rejected: pinning by tag/branch/sha is required for
reproducibility (see ADR / plan for #726).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Anchored shorthand parser: org/repo@version. Disallows whitespace, slashes
# and @ inside org/repo so we never match a full URL by accident.
_GITHUB_SHORTHAND_RE = re.compile(r"^([^/@\s]+)/([^/@\s]+)@(.+)$")

# URL prefixes that mean "treat the whole string as <url>@<version>" and
# split on the LAST @, since ssh forms like git@host: and git+ssh://git@host
# already contain an @ before the version.
_URL_PREFIXES = (
    "http://",
    "https://",
    "git+ssh://",
    "ssh://",
    "git://",
    "git@",
)

# Bare-host shorthand like "github.com/org/repo" expands to https://.
_BARE_HOST_RE = re.compile(r"^[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/")


def _basename_from_url(url: str) -> str:
    """Compute display name from a URL: last path segment minus ``.git`` suffix."""
    # Strip protocol and anything before the last "/" or ":" (SSH form like git@host:org/repo).
    tail = url.rstrip("/")
    for sep in ("/", ":"):
        idx = tail.rfind(sep)
        if idx >= 0:
            tail = tail[idx + 1 :]
            break
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail


def _normalize_source(source: str) -> str:
    """Expand bare-host shorthand to https://; pass full URLs through."""
    if source.startswith(_URL_PREFIXES):
        return source
    if _BARE_HOST_RE.match(source):
        return f"https://{source}"
    return source


def _parse_string_form(raw: str) -> dict[str, Any]:
    """Parse the two string forms (GitHub shorthand and full URL@version)."""
    raw = raw.strip()
    if not raw:
        msg = "claude plugin reference cannot be empty"
        raise ValueError(msg)

    # Form A: github shorthand ``org/repo@version``.
    # Try this first - fails fast for full URLs because they contain "://".
    if "://" not in raw and not raw.startswith("git@"):
        match = _GITHUB_SHORTHAND_RE.match(raw)
        if match:
            org, repo, version = match.group(1), match.group(2), match.group(3)
            return {
                "name": repo,
                "source_url": f"https://github.com/{org}/{repo}",
                "version": version,
                "name_overridden": False,
            }

    # Form B: full URL with version suffix. Split on LAST @ because git@host:
    # and git+ssh://git@host both contain @ before any version delimiter.
    if raw.startswith(_URL_PREFIXES):
        last_at = raw.rfind("@")
        # Reject if the @ is part of the protocol prefix itself
        # (e.g. "git@host" with no version).
        if last_at < 0 or last_at < len("git@"):
            msg = (
                f"claude plugin reference {raw!r} is missing '@<version>' suffix; "
                "expected '<url>@<tag-or-sha>'"
            )
            raise ValueError(msg)
        # Defend against the @ being inside the prefix (e.g. just "git@host:org/repo"
        # with no trailing version).
        url_part = raw[:last_at]
        version = raw[last_at + 1 :]
        if not version:
            msg = f"claude plugin reference {raw!r} has empty version after '@'"
            raise ValueError(msg)
        # If the "version" still contains a "/" or "://" it almost certainly is part
        # of the URL, meaning no version was provided.
        if "://" in version or "/" in version:
            msg = (
                f"claude plugin reference {raw!r} is missing '@<version>' suffix; "
                "expected '<url>@<tag-or-sha>'"
            )
            raise ValueError(msg)
        return {
            "name": _basename_from_url(url_part),
            "source_url": url_part,
            "version": version,
            "name_overridden": False,
        }

    msg = (
        f"claude plugin reference {raw!r} is not a recognized form; "
        "expected 'org/repo@version' or '<url>@<version>' or a verbose mapping"
    )
    raise ValueError(msg)


def _parse_dict_form(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse the verbose mapping form."""
    # Accept either ``source`` or ``source_url`` for ergonomic flexibility.
    source_value = raw.get("source") or raw.get("source_url")
    version_value = raw.get("version")
    explicit_name = raw.get("name")

    if not source_value or not isinstance(source_value, str):
        msg = "claude plugin verbose form requires non-empty 'source' (or 'source_url')"
        raise ValueError(msg)
    if not version_value or not isinstance(version_value, str):
        msg = "claude plugin verbose form requires non-empty 'version'"
        raise ValueError(msg)

    source_url = _normalize_source(source_value.strip())
    name = (
        explicit_name.strip()
        if isinstance(explicit_name, str) and explicit_name.strip()
        else _basename_from_url(source_url)
    )
    return {
        "name": name,
        "source_url": source_url,
        "version": version_value.strip(),
        "name_overridden": isinstance(explicit_name, str) and bool(explicit_name.strip()),
    }


class ClaudePluginRef(BaseModel):
    """A workflow-declared reference to a Claude Code plugin.

    Compared and hashed by ``(source_url, version)`` only - name overrides
    do not affect identity, so a workflow-scope ref and a phase-scope ref
    pointing at the same plugin dedup cleanly into one lock entry.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1)
    source_url: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    name_overridden: bool = False

    @model_validator(mode="before")
    @classmethod
    def _coerce_input(cls, value: object) -> object:
        # Already-validated dict shape (e.g. round-trip through model_dump) - let
        # field validators handle it after we still reject @latest below.
        if isinstance(value, str):
            value = _parse_string_form(value)
        elif isinstance(value, dict):
            keys = set(value.keys())  # type: ignore[arg-type]
            # Distinguish the verbose YAML form from a fully-built model dump.
            # A dump always has the canonical fields exactly; the verbose form has
            # ``source`` (or ``source_url`` without the other canonical fields).
            if "source" in keys or ("source_url" in keys and "name" not in keys):
                value = _parse_dict_form(value)  # type: ignore[arg-type]

        # Reject @latest regardless of how we got here - defeats the lockfile.
        if isinstance(value, dict):
            version = value.get("version")
            if isinstance(version, str) and version.strip().lower() == "latest":
                msg = (
                    "claude plugin version must be a specific tag/branch/sha; "
                    "'@latest' is not allowed for reproducibility"
                )
                raise ValueError(msg)
        return value

    def __eq__(self, other: object) -> bool:
        # Identity is the lock key, NOT the user-visible name. This lets
        # workflow- and phase-scope refs to the same plugin dedupe cleanly.
        if not isinstance(other, ClaudePluginRef):
            return NotImplemented
        return self.source_url == other.source_url and self.version == other.version

    def __hash__(self) -> int:
        return hash((self.source_url, self.version))
