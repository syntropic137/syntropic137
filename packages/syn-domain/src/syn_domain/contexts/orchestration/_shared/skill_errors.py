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
- ``SkillInstallFailed`` raised by ``WorkspaceProvisionHandler`` when a
  phase's skills do not get installed - either the in-container ``skills
  add`` ended badly, or the install was refused before it ran.

The previous ``SkillSourceUnreachable`` / ``SkillVersionNotFound`` /
``SkillAuthRequired`` errors were CLI-emitted (git clone failures) and
no longer exist at the API tier; the CLI surfaces those failures locally before
ever calling the API.
"""

from __future__ import annotations

from syn_shared.process_exit import describe_process_failure


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
    """A phase's skills did not get installed, said in a way that survives.

    This message is persisted as the execution's ``error_message``, so it has
    the same duty as the setup phase's (#1158): say how the install ENDED
    before quoting what it printed. ``skills add`` writes progress to stderr
    too, so an install killed at the phase timeout was recorded as "failed
    (exit -1): Fetching skill ..." - an exit status that says nothing, in
    front of a reason that is a download going normally.

    Constructed by KIND of failure, never by formatting a message at the call
    site. There are two kinds and they are not the same fact: an install that
    ran and ended badly, and one that was refused before anything ran. The
    second used to be spelled ``exit_code=-1`` with a hand-written explanation
    passed as ``stderr`` - process-shaped fields for something that was never
    a process, which is how it came to read as a command that failed.
    """

    error_code = "skill_install_failed"
    exit_code: int

    #: What an operator can read before the message stops being a message.
    #: ``skills add`` can print a great deal and this text is stored per
    #: execution; the bound predates #1158 and is kept.
    _OUTPUT_LIMIT = 500

    @classmethod
    def after_exit(
        cls,
        skill_name: str,
        agent: str,
        *,
        exit_code: int,
        output: str,
        timed_out: bool = False,
    ) -> SkillInstallFailed:
        """The in-container ``skills add`` ran and did not succeed."""
        failure = cls(
            describe_process_failure(
                f"installing skill {skill_name!r} for agent {agent!r}",
                exit_code=exit_code,
                output=output.strip()[: cls._OUTPUT_LIMIT],
                timed_out=timed_out,
            )
        )
        failure.exit_code = exit_code
        return failure

    @classmethod
    def not_attempted(cls, skill_name: str, reason: str) -> SkillInstallFailed:
        """Nothing ran, so `reason` is the whole of it and no status is invented."""
        return cls(f"installing skill {skill_name!r} was not attempted: {reason}")
