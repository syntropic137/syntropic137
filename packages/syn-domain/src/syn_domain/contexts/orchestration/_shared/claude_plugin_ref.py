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
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _ParsedRefDict(TypedDict):
    """Canonical dict shape produced by all ref parsers before model validation."""

    name: str
    source_url: str
    version: str
    name_overridden: bool


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


def _try_parse_github_shorthand(raw: str) -> _ParsedRefDict | None:
    """Form A parser: ``org/repo@version``. Returns ``None`` if not a match.

    WHY: full URLs contain ``://`` or ``git@`` and are routed to Form B; this
    helper fails fast on those without consulting the regex.
    """
    if "://" in raw or raw.startswith("git@"):
        return None
    match = _GITHUB_SHORTHAND_RE.match(raw)
    if match is None:
        return None
    org, repo, version = match.group(1), match.group(2), match.group(3)
    return {
        "name": repo,
        "source_url": f"https://github.com/{org}/{repo}",
        "version": version,
        "name_overridden": False,
    }


def _missing_version_error(raw: str) -> ValueError:
    return ValueError(
        f"claude plugin reference {raw!r} is missing '@<version>' suffix; "
        "expected '<url>@<tag-or-sha>'"
    )


def _parse_url_form(raw: str) -> _ParsedRefDict:
    """Form B parser: ``<url>@<version>``.

    WHY split on LAST @: git@host: and git+ssh://git@host both contain @ before
    any version delimiter. We also defend against an @ that is purely part of
    the protocol prefix (no real version) and against a "version" that is
    actually still part of the URL (contains "/" or "://").
    """
    last_at = raw.rfind("@")
    if last_at < 0 or last_at < len("git@"):
        raise _missing_version_error(raw)
    url_part = raw[:last_at]
    version = raw[last_at + 1 :]
    if not version:
        msg = f"claude plugin reference {raw!r} has empty version after '@'"
        raise ValueError(msg)
    if "://" in version or "/" in version:
        raise _missing_version_error(raw)
    return {
        "name": _basename_from_url(url_part),
        "source_url": url_part,
        "version": version,
        "name_overridden": False,
    }


def _parse_string_form(raw: str) -> _ParsedRefDict:
    """Parse the two string forms (GitHub shorthand and full URL@version)."""
    raw = raw.strip()
    if not raw:
        msg = "claude plugin reference cannot be empty"
        raise ValueError(msg)

    shorthand = _try_parse_github_shorthand(raw)
    if shorthand is not None:
        return shorthand

    if raw.startswith(_URL_PREFIXES):
        return _parse_url_form(raw)

    msg = (
        f"claude plugin reference {raw!r} is not a recognized form; "
        "expected 'org/repo@version' or '<url>@<version>' or a verbose mapping"
    )
    raise ValueError(msg)


def _parse_dict_form(raw: dict[str, Any]) -> _ParsedRefDict:
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


def _is_verbose_dict_form(value: dict[Any, Any]) -> bool:
    """Distinguish the verbose YAML form from a fully-built model dump.

    WHY: a model dump always has the canonical fields exactly; the verbose
    form has ``source`` (or ``source_url`` without the other canonical fields).
    """
    keys = set(value.keys())
    return "source" in keys or ("source_url" in keys and "name" not in keys)


def _coerce_to_canonical_dict(value: object) -> object:
    if isinstance(value, str):
        return _parse_string_form(value)
    if isinstance(value, dict) and _is_verbose_dict_form(value):
        return _parse_dict_form(value)
    return value


def _reject_latest_version(value: object) -> None:
    """Reject @latest regardless of how we got here -- defeats the lockfile."""
    if not isinstance(value, dict):
        return
    version = value.get("version")
    if isinstance(version, str) and version.strip().lower() == "latest":
        msg = (
            "claude plugin version must be a specific tag/branch/sha; "
            "'@latest' is not allowed for reproducibility"
        )
        raise ValueError(msg)


class ClaudePluginRef(BaseModel):
    """A workflow-declared reference to a Claude Code plugin.

    Compared and hashed by ``(source_url, version, name)`` to match the lock
    projection key (issue #726). A workflow author who installs the same
    plugin under two different display names produces two distinct lock
    entries -- the materializer needs both to write the right files.
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
        coerced = _coerce_to_canonical_dict(value)
        _reject_latest_version(coerced)
        return coerced

    def __eq__(self, other: object) -> bool:
        # Identity is the lock projection key: (source_url, version, name).
        # WHY include name: a marketplace repo can publish multiple plugins,
        # and the same (source_url, version) registered under two different
        # names must produce two distinct lock entries so the materializer
        # writes the correct file set for each.
        if not isinstance(other, ClaudePluginRef):
            return NotImplemented
        return (
            self.source_url == other.source_url
            and self.version == other.version
            and self.name == other.name
        )

    def __hash__(self) -> int:
        return hash((self.source_url, self.version, self.name))
