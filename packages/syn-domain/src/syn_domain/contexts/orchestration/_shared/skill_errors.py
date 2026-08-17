# See ADR-066: typed domain errors live in syn-domain because they are part of
# the application contract; only manifest validation, safety, and
# registry-lookup errors remain after Phase A (#772). Source/version/auth
# fetch errors are CLI-tier concerns now (the API does no git work) and were
# dropped from this module.
"""Typed errors for the skill injection feature (issue #772).

After the #772 Phase A redesign, these error families remain at the API tier:

- ``SkillManifestMissing`` / ``SkillManifestInvalid`` raised by
  ``RegisterSkillHandler`` when the uploaded tree is missing a root
  SKILL.md, or its frontmatter fails to parse or validate.
- ``SkillInvalidPath`` raised by ``RegisterSkillHandler`` when a file's
  ``rel_path`` in the uploaded tree fails safety validation.
- ``SkillInvalidName`` raised by ``skill_materializer`` when a registered
  skill's name fails workspace-path safety validation.
- ``SkillNotRegistered`` raised by ``SkillResolutionService`` when a
  workflow references a skill that has not yet been registered via
  ``POST /skills/registrations``.
- ``SkillInstallFailed`` raised by ``WorkspaceProvisionHandler`` when the
  in-container ``skills add`` invocation exits nonzero.

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
    """The uploaded tree does not contain a root SKILL.md file."""

    error_code = "not_a_skill"

    def __init__(self, source_url: str, version: str) -> None:
        super().__init__(f"Skill tree at {source_url}@{version} is missing a root SKILL.md file")
        self.source_url = source_url
        self.version = version


class SkillManifestInvalid(SkillError):
    """The SKILL.md frontmatter exists but failed to parse or validate."""

    error_code = "skill_manifest_invalid"

    def __init__(self, source_url: str, version: str, detail: str) -> None:
        super().__init__(f"SKILL.md frontmatter for {source_url}@{version} is invalid: {detail}")
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


class SkillVersionHashMismatch(SkillError):
    """A ``sha256-<hash>`` version does not match the submitted tree's hash.

    Such a version is a content commitment, not a label: bundled skills are
    pinned this way, so their identity rests on it holding. Without this check
    a caller could register arbitrary content under a version naming another
    tree's hash, and every later install resolving that triple would receive
    the substituted content (issue #772).
    """

    error_code = "skill_version_hash_mismatch"

    def __init__(self, source_url: str, declared: str, actual_sha: str) -> None:
        super().__init__(
            f"Skill version {declared!r} for {source_url!r} claims a content hash, but the "
            f"submitted tree hashes to {actual_sha!r}. A 'sha256-<hash>' version must match "
            "the content it names."
        )
        self.source_url = source_url
        self.declared = declared
        self.actual_sha = actual_sha


class SkillNotRegistered(SkillError):
    """A workflow declared a skill that has no lock entry."""

    error_code = "skill_not_registered"

    def __init__(self, source_url: str, version: str, skill_name: str) -> None:
        super().__init__(
            f"skill {skill_name!r} from {source_url}@{version} is not registered; "
            "register it first (Plan 2: 'syn skill add', or POST /skills/registrations)"
        )
        self.source_url = source_url
        self.version = version
        self.skill_name = skill_name


class SkillInstallFailed(SkillError):
    """The in-container 'skills add' invocation exited nonzero."""

    error_code = "skill_install_failed"

    def __init__(self, skill_name: str, agent: str, exit_code: int, stderr: str) -> None:
        super().__init__(
            f"installing skill {skill_name!r} for agent {agent!r} failed "
            f"(exit {exit_code}): {stderr.strip()[:500]}"
        )
