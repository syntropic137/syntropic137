"""Workflow-author-facing reference to an agent skill (issue #772).

A ``SkillRef`` is what appears in workflow YAML under the ``skills:``
field at workflow- and phase-scope. It is the *declared* reference
(source + version), prior to any resolution against the lock
projection. This mirrors ``ClaudePluginRef`` (issue #726) but is
harness-agnostic: skills are plain markdown/instructions, not tied to
Claude Code's plugin mechanism.

Three input forms are accepted (validator normalizes to one shape):

1. GitHub shorthand string ``"org/repo/skill-name@version"``. The third
   path segment names the skill folder inside the repo -- required
   because a skills repo commonly publishes many skills.
2. Full URL string ``"<url>@<version>"``. Names the repo only; the
   skill name defaults to the URL basename (single-skill repos).
3. Verbose mapping with ``source`` (or ``source_url``), ``version``, and
   optional explicit ``name`` override, or ``names: [a, b]`` to expand
   into multiple refs sharing the same source and version.

``@latest`` is rejected: pinning by tag/branch/sha is required for
reproducibility (see ADR / plan for #772).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from pydantic import GetJsonSchemaHandler
    from pydantic.json_schema import JsonSchemaValue
    from pydantic_core import CoreSchema


class _ParsedRefDict(TypedDict):
    """Canonical dict shape produced by all ref parsers before model validation."""

    skill_name: str
    source_url: str
    version: str
    name_overridden: bool


# Opaque SKILL.md frontmatter payload (issue #772). Author-defined keys, no
# closed schema -- a single named alias avoids repeating the same annotation
# across the aggregate, command, event, and handler layers that all pass this
# payload through unopened. Mapping (not dict): every consumer only reads it;
# copies are made explicitly with dict(...) where mutation is needed.
SkillManifest = Mapping[str, object]


class _VerboseSkillInput(TypedDict, total=False):
    """Raw verbose mapping form as authored in workflow YAML.

    All keys are optional at this stage -- ``_parse_dict_form`` validates
    presence/type before producing a ``_ParsedRefDict``.
    """

    source: str
    source_url: str
    version: str
    name: str
    names: list[str]


# Anchored shorthand parser: org/repo/skill-name@version.
_SKILL_SHORTHAND_RE = re.compile(r"^([^/@\s]+)/([^/@\s]+)/([^/@\s]+)@(.+)$")

# Two-segment form is a plugin-era shape; give a corrective error.
_TWO_SEGMENT_RE = re.compile(r"^([^/@\s]+)/([^/@\s]+)@(.+)$")

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


def _try_parse_skill_shorthand(raw: str) -> _ParsedRefDict | None:
    """Form A parser: ``org/repo/skill-name@version``. Returns ``None`` if not a match.

    WHY: full URLs contain ``://`` or ``git@`` and are routed to Form B; this
    helper fails fast on those without consulting the regex.
    """
    if "://" in raw or raw.startswith("git@"):
        return None
    if _BARE_HOST_RE.match(raw):
        msg = (
            f"skill reference {raw!r} looks like a host-qualified path; "
            "use the full URL form '<url>@<version>' or the verbose mapping form"
        )
        raise ValueError(msg)
    match = _SKILL_SHORTHAND_RE.match(raw)
    if match is not None:
        org, repo, skill, version = match.groups()
        return {
            "skill_name": skill,
            "source_url": f"https://github.com/{org}/{repo}",
            "version": version,
            "name_overridden": False,
        }
    if _TWO_SEGMENT_RE.match(raw) is not None:
        msg = (
            f"skill reference {raw!r} names a repo but not a skill; "
            "expected 'org/repo/skill-name@version' or the verbose mapping form"
        )
        raise ValueError(msg)
    return None


def _missing_version_error(raw: str) -> ValueError:
    return ValueError(
        f"skill reference {raw!r} is missing '@<version>' suffix; expected '<url>@<tag-or-sha>'"
    )


def _slash_in_version_error(raw: str) -> ValueError:
    # WHY reject rather than parse: a "/" in the version is inherently
    # ambiguous in the compact '<url>@<version>' string form -- we cannot
    # tell whether it is still part of the URL or a slash-containing version
    # like a branch pin ('feature/foo'). The verbose mapping form ('source'/
    # 'version' keys) has no such ambiguity because the two fields are
    # already split, so it accepts slash-containing versions.
    return ValueError(
        f"skill reference {raw!r} has a '/' in the version segment, which is "
        "ambiguous in the '<url>@<version>' string form; use the verbose "
        "mapping form ('source'/'version' keys) to express versions "
        "containing '/' (e.g. a branch pin like 'feature/foo')"
    )


def _ambiguous_at_error(raw: str) -> ValueError:
    # WHY reject rather than parse: splitting on the LAST '@' silently
    # corrupts the pin when the ref name itself contains '@' (e.g. a git
    # tag literally named 'release@2026') -- 'https://.../skills@release@2026'
    # would parse as source_url '.../skills@release' + version '2026', a
    # different identity than the author declared. We only tolerate the
    # single '@' used by the ssh user-info prefix (git@host, ssh://git@host,
    # git+ssh://git@host); any other residual '@' must be disambiguated
    # explicitly.
    return ValueError(
        f"skill reference {raw!r} has an ambiguous '@' (the ref name itself "
        "contains '@'); use the verbose mapping form with separate source "
        "and version"
    )


def _check_no_ambiguous_at(raw: str, url_part: str) -> None:
    """Reject a residual '@' in ``url_part`` beyond the ssh-user prefix.

    ``url_part`` is everything before the last '@' in the raw string. It is
    expected to start with a recognized URL prefix (the caller only invokes
    this after confirming that). Strip that prefix, then strip one leading
    'git@' ssh user-info segment if present, then anything left over is an
    '@' that came from the ref name itself.
    """
    remainder = url_part
    for prefix in ("git+ssh://", "ssh://", "git://", "https://", "http://", "git@"):
        if remainder.startswith(prefix):
            remainder = remainder[len(prefix) :]
            break
    if remainder.startswith("git@"):
        remainder = remainder[len("git@") :]
    if "@" in remainder:
        raise _ambiguous_at_error(raw)


def _parse_url_form(raw: str) -> _ParsedRefDict:
    """Form B parser: ``<url>@<version>``.

    WHY split on LAST @: git@host: and git+ssh://git@host both contain @ before
    any version delimiter. We also defend against an @ that is purely part of
    the protocol prefix (no real version) and against a "version" that is
    actually still part of the URL (contains "/" or "://"). Any further '@'
    in url_part beyond the recognized ssh-user prefix means the ref name
    itself contains '@' -- see ``_check_no_ambiguous_at``.
    """
    last_at = raw.rfind("@")
    if last_at < 0 or last_at < len("git@"):
        raise _missing_version_error(raw)
    url_part = raw[:last_at]
    version = raw[last_at + 1 :]
    if not version:
        msg = f"skill reference {raw!r} has empty version after '@'"
        raise ValueError(msg)
    if "://" in version:
        raise _missing_version_error(raw)
    if "/" in version:
        raise _slash_in_version_error(raw)
    _check_no_ambiguous_at(raw, url_part)
    return {
        "skill_name": _basename_from_url(url_part),
        "source_url": url_part,
        "version": version,
        "name_overridden": False,
    }


def _parse_string_form(raw: str) -> _ParsedRefDict:
    """Parse the two string forms (GitHub shorthand and full URL@version)."""
    raw = raw.strip()
    if not raw:
        msg = "skill reference cannot be empty"
        raise ValueError(msg)

    shorthand = _try_parse_skill_shorthand(raw)
    if shorthand is not None:
        return shorthand

    if raw.startswith(_URL_PREFIXES):
        return _parse_url_form(raw)

    msg = (
        f"skill reference {raw!r} is not a recognized form; "
        "expected 'org/repo/skill-name@version' or '<url>@<version>' or a verbose mapping"
    )
    raise ValueError(msg)


def _parse_dict_form(raw: _VerboseSkillInput) -> _ParsedRefDict:
    """Parse the verbose mapping form."""
    # Accept either ``source`` or ``source_url`` for ergonomic flexibility.
    source_value = raw.get("source") or raw.get("source_url")
    version_value = raw.get("version")
    explicit_name = raw.get("name")

    if not source_value or not isinstance(source_value, str):
        msg = "skill verbose form requires non-empty 'source' (or 'source_url')"
        raise ValueError(msg)
    if not version_value or not isinstance(version_value, str):
        msg = "skill verbose form requires non-empty 'version'"
        raise ValueError(msg)

    source_url = _normalize_source(source_value.strip())
    skill_name = (
        explicit_name.strip()
        if isinstance(explicit_name, str) and explicit_name.strip()
        else _basename_from_url(source_url)
    )
    return {
        "skill_name": skill_name,
        "source_url": source_url,
        "version": version_value.strip(),
        "name_overridden": isinstance(explicit_name, str) and bool(explicit_name.strip()),
    }


def _is_verbose_dict_form(value: dict[object, object]) -> bool:
    """Distinguish the verbose YAML form from a fully-built model dump.

    WHY: a model dump always has the canonical fields exactly; the verbose
    form has ``source`` (or ``source_url`` without the other canonical fields).
    """
    keys = set(value.keys())
    return "source" in keys or ("source_url" in keys and "skill_name" not in keys)


def _coerce_to_canonical_dict(value: object) -> object:
    if isinstance(value, str):
        return _parse_string_form(value)
    if isinstance(value, dict) and _is_verbose_dict_form(value):
        # Untyped input crossing a trust boundary (workflow YAML) -- shape is
        # runtime-validated inside _parse_dict_form, not just asserted here.
        return _parse_dict_form(cast("_VerboseSkillInput", value))
    return value


def _reject_latest_version(value: object) -> None:
    """Reject @latest regardless of how we got here -- defeats the lockfile."""
    if not isinstance(value, dict):
        return
    version = value.get("version")
    if isinstance(version, str) and version.strip().lower() == "latest":
        msg = (
            "skill version must be a specific tag/branch/sha; "
            "'@latest' is not allowed for reproducibility"
        )
        raise ValueError(msg)


class SkillRef(BaseModel):
    """A workflow-declared reference to an agent skill (issue #772).

    Compared and hashed by ``(source_url, version, skill_name)`` to match
    the lock projection key. A repo publishing many skills produces one
    ref (and one lock entry) per declared skill.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str = Field(..., min_length=1)
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

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        """Publish an ``anyOf`` schema covering every accepted input form.

        WHY: the model-validator accepts string shorthand
        (``org/repo/skill-name@version``, ``<url>@<version>``) and the
        verbose mapping (``source``/``source_url`` + ``version`` +
        optional ``name``), but pydantic's default schema only describes
        the canonical object shape. Editors and CI validating workflow
        YAML against the generated ``workflow.schema.json`` would reject
        the documented string examples.
        """
        json_schema = handler(core_schema)
        resolved = handler.resolve_ref_schema(json_schema)
        description = resolved.get(
            "description",
            "A workflow-declared reference to an agent skill.",
        )
        resolved.clear()
        resolved.update(
            {
                "title": "SkillRef",
                "description": description,
                "anyOf": [
                    {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Shorthand form: 'org/repo/skill-name@version' or "
                            "'<url>@<version>'. '@latest' is rejected."
                        ),
                    },
                    {
                        "type": "object",
                        "description": (
                            "Verbose mapping form: 'source' (or 'source_url') "
                            "plus 'version', with an optional 'name' override "
                            "or 'names' list to expand into multiple refs."
                        ),
                        "properties": {
                            "source": {"type": "string", "minLength": 1},
                            "source_url": {"type": "string", "minLength": 1},
                            "version": {"type": "string", "minLength": 1},
                            "name": {"type": "string", "minLength": 1},
                            "names": {
                                "type": "array",
                                "items": {"type": "string", "minLength": 1},
                                "minItems": 1,
                            },
                            "name_overridden": {"type": "boolean"},
                        },
                        "required": ["version"],
                        "anyOf": [
                            {"required": ["source"]},
                            {"required": ["source_url"]},
                        ],
                        "additionalProperties": False,
                    },
                ],
            }
        )
        return json_schema

    def __eq__(self, other: object) -> bool:
        # Identity is the lock projection key: (source_url, version, skill_name).
        # WHY include skill_name: a marketplace repo can publish multiple
        # skills, and the same (source_url, version) registered under two
        # different names must produce two distinct lock entries so the
        # materializer writes the correct file set for each.
        if not isinstance(other, SkillRef):
            return NotImplemented
        return (
            self.source_url == other.source_url
            and self.version == other.version
            and self.skill_name == other.skill_name
        )

    def __hash__(self) -> int:
        return hash((self.source_url, self.version, self.skill_name))


def expand_skill_entry(entry: object) -> list[SkillRef]:
    """Expand one YAML ``skills:`` list entry into one or more SkillRefs.

    The verbose mapping form accepts ``names: [a, b]`` to declare several
    skills from one source; every other form yields exactly one ref.
    """
    if isinstance(entry, dict) and "names" in entry:
        names = entry["names"]
        if not isinstance(names, list) or not names:
            msg = "skill verbose form 'names' must be a non-empty list of strings"
            raise ValueError(msg)
        base = {k: v for k, v in entry.items() if k != "names"}
        return [SkillRef.model_validate({**base, "name": name}) for name in names]
    return [SkillRef.model_validate(entry)]
