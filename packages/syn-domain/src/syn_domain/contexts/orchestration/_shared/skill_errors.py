# See ADR-066: typed domain errors live in syn-domain because they are part of
# the application contract; only manifest validation and registry-lookup errors
# remain after Phase A (#772). Source/version/auth fetch errors are CLI-tier
# concerns now (the API does no git work) and were dropped from this module.
"""Typed errors for the skill injection feature (issue #772).

After the #772 Phase A redesign, only two error families remain at the API
tier:

- Manifest validation errors raised by ``RegisterSkillHandler`` when
  the uploaded tree is missing or has a malformed ``.syn-skill/skill.json``.
- ``SkillNotRegistered`` raised by ``AddGlobalSkillHandler`` and
  ``SkillResolutionService`` when a referenced skill has not yet been
  registered via ``POST /skills/registrations``.

The previous ``SkillSourceUnreachable`` / ``SkillVersionNotFound`` /
``SkillAuthRequired`` errors were CLI-emitted (git clone failures) and
no longer exist at the API tier; the CLI surfaces those failures locally before
ever calling the API.
"""

from __future__ import annotations


class SkillError(Exception):
    """Base class for skill registration errors."""

    error_code: str = "skill_error"


class SkillManifestMissing(SkillError):
    """The uploaded tree does not contain `.syn-skill/skill.json`."""

    error_code = "not_a_skill"

    def __init__(self, source_url: str, version: str) -> None:
        super().__init__(
            f"Source {source_url}@{version} is not a skill "
            f"(missing .syn-skill/skill.json)"
        )
        self.source_url = source_url
        self.version = version


class SkillManifestInvalid(SkillError):
    """The skill.json exists but failed to parse or validate."""

    error_code = "skill_manifest_invalid"

    def __init__(self, source_url: str, version: str, detail: str) -> None:
        super().__init__(f"Invalid skill.json in {source_url}@{version}: {detail}")
        self.source_url = source_url
        self.version = version
        self.detail = detail


class SkillInvalidName(SkillError):
    """A skill name fails workspace-path safety validation.

    Raised at the materialization boundary when a registered skill's name
    would be unsafe to interpolate into a workspace-relative path (issue
    #772). Path-traversal, absolute-path, control-character, and empty names
    are rejected so the materializer cannot escape ``.syn-skills/<skill_name>/``.
    """

    error_code = "skill_invalid_name"

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(
            f"Skill name {name!r} is invalid: {reason}. "
            "Names must be a single path segment without separators, traversal, "
            "control characters, or leading dots."
        )
        self.name = name
        self.reason = reason


class SkillInvalidPath(SkillError):
    """A file path in the uploaded skill tree fails safety validation.

    Raised by ``RegisterSkillHandler`` before any hashing or storage
    so a hostile ``rel_path`` (traversal, absolute, backslash, control
    characters) can never be persisted and later materialized into a
    workspace path (issue #772).
    """

    error_code = "skill_invalid_path"

    def __init__(self, rel_path: str, reason: str) -> None:
        super().__init__(
            f"Skill file path {rel_path!r} is invalid: {reason}. "
            "Paths must be POSIX-relative with no empty or '.'/'..' segments, "
            "no backslashes, and no control characters."
        )
        self.rel_path = rel_path
        self.reason = reason


class SkillNotRegistered(SkillError):
    """A workflow declared a skill that has no lock entry."""

    error_code = "skill_not_registered"

    def __init__(self, source_url: str, version: str, skill_name: str) -> None:
        super().__init__(
            f"skill {skill_name!r} from {source_url}@{version} is not registered; "
            "register it first (Plan 2: 'syn skill add', or POST /skills/registrations)"
        )


class SkillInstallFailed(SkillError):
    """The in-container 'skills add' invocation exited nonzero."""

    error_code = "skill_install_failed"

    def __init__(self, skill_name: str, agent: str, exit_code: int, stderr: str) -> None:
        super().__init__(
            f"installing skill {skill_name!r} for agent {agent!r} failed "
            f"(exit {exit_code}): {stderr.strip()[:500]}"
        )
