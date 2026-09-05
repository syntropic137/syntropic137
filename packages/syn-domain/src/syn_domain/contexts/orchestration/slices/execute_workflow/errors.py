"""Error types for workflow execution (ISS-196).

Extracted from WorkflowExecutionEngine during M6 cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


class WorkflowNotFoundError(Exception):
    """Raised when a workflow is not found."""

    def __init__(self, workflow_id: str) -> None:
        super().__init__(f"Workflow not found: {workflow_id}")
        self.workflow_id = workflow_id


class DuplicateExecutionError(Exception):
    """Raised when an execution with this ID already exists.

    This is the idempotency guard: if the event store already has a stream
    for this execution_id, a duplicate dispatch was attempted. Callers
    should treat this as a no-op (the execution is already running).
    """

    def __init__(self, execution_id: str) -> None:
        super().__init__(f"Execution already exists: {execution_id}")
        self.execution_id = execution_id


class WorkflowExecutionError(Exception):
    """Raised when workflow execution fails."""

    def __init__(
        self,
        message: str,
        workflow_id: str,
        phase_id: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.workflow_id = workflow_id
        self.phase_id = phase_id
        self.__cause__ = cause


class WorkflowInterruptedError(Exception):
    """Raised when workflow execution is forcefully interrupted via SIGINT.

    Carries partial state captured at the time of interruption so the engine
    can persist a WorkflowInterruptedEvent with meaningful data.
    """

    def __init__(
        self,
        phase_id: str,
        reason: str | None = None,
        git_sha: str | None = None,
        partial_artifact_ids: list[str] | None = None,
        partial_input_tokens: int = 0,
        partial_output_tokens: int = 0,
    ) -> None:
        super().__init__(f"Execution interrupted in phase {phase_id}: {reason}")
        self.phase_id = phase_id
        self.reason = reason
        self.git_sha = git_sha
        self.partial_artifact_ids = partial_artifact_ids or []
        self.partial_input_tokens = partial_input_tokens
        self.partial_output_tokens = partial_output_tokens


class UnsupportedToolPolicyForProviderError(ValueError):
    """A phase declared allowed_tools for a provider that cannot honour them.

    The domain-side twin of the command builder's `UnsupportedToolPolicyError`.
    It exists separately because it fires EARLIER - at the execution boundary,
    before a workspace is provisioned - and the builder's version cannot be
    imported here without the domain depending on the composition layer.
    """

    def __init__(
        self,
        *,
        provider: str,
        phase_id: str | None,
        declared: list[str],
    ) -> None:
        where = f"Phase '{phase_id}': " if phase_id else ""
        super().__init__(
            f"{where}provider '{provider}' cannot honour allowed_tools "
            f"({', '.join(declared)}). It enforces a filesystem sandbox, not a "
            "tool vocabulary, so the list would be accepted and never applied. "
            "Remove allowed_tools, or run this phase on 'claude'."
        )


class PhaseProducedNoDeclaredOutputError(Exception):
    """A phase declared output artifact types and produced none of them (#1167).

    THE FAILURE THIS EXISTS TO STOP. A phase could finish with
    status=completed, error_message=None and artifact_id=None - none of the
    output its contract declares - and the execution advanced as though it had
    succeeded. Four real executions did exactly that; in one the phase that
    vanished was `verify`, so the review gate was silently removed from the run
    while every surface still reported completed.

    WHY THE DECLARATION IS THE TEST, not "did it write anything". A phase that
    declares no output types is legitimately allowed to produce nothing - the
    self-host validation workflows have four such phases, which answer a
    question and stop. Only a declared-but-unproduced output is a failure, so
    an empty declaration is silence, not a violation.

    Raised from ArtifactCollector.collect_from_workspace, which is the one
    place holding both halves of the comparison: what the phase promised and
    what it actually wrote.
    """

    def __init__(
        self,
        *,
        phase_id: str,
        phase_name: str,
        declared: tuple[str, ...],
    ) -> None:
        super().__init__(
            f"Phase '{phase_id}' ({phase_name}) declares output_artifacts "
            f"({', '.join(declared)}) but produced none: nothing collectable "
            f"was written under artifacts/output/. The phase's contract is "
            f"unmet, so the execution fails here rather than advancing as "
            f"though it had succeeded."
        )
        self.phase_id = phase_id
        self.phase_name = phase_name
        self.declared = declared


@dataclass(frozen=True)
class FailedWorkspaceCommand:
    """The command that did not run, in enough detail to tell why."""

    command: tuple[str, ...]
    exit_code: int
    stderr: str
    timed_out: bool = False


class WorkspaceInspectionFailedError(Exception):
    """The gate could not read the workspace, so it refused to call it clean (#1184).

    THE FAILURE THIS EXISTS TO STOP, and it is #1184 wearing a disguise. The
    unpushed-work gate answers "is anything here about to be lost" by running
    commands in the workspace and reading their stdout. An unreachable
    container does not raise: the Docker backend RETURNS a non-zero
    ``ExecutionResult`` with empty stdout. Empty stdout is also exactly what a
    genuinely clean workspace produces. So without this error the two states
    were one value, the gate returned silently, and the phase was reported
    ``completed`` with its work already gone - the precise outcome the gate was
    written to prevent, reproduced inside the gate.

    A failed command has no output, so there is nothing to parse and no verdict
    to give. Refusing to guess is the whole content of this error.

    WHAT IT DOES NOT CLAIM. Nothing has been quarantined when this is raised.
    Raising stops a false ``completed``; it cannot reach into a container that
    is already gone and make what was inside it durable. The work this phase
    held is unverified, and may already be unrecoverable.
    """

    def __init__(self, *, doing: str, failure: FailedWorkspaceCommand) -> None:
        self.doing = doing
        self.failure = failure
        super().__init__(_render_inspection_failure(doing, failure))


def _render_inspection_failure(doing: str, failure: FailedWorkspaceCommand) -> str:
    why = "timed out, so it did not finish" if failure.timed_out else f"exited {failure.exit_code}"
    stderr = failure.stderr.strip()
    return (
        f"The unpushed-work gate could not verify this phase's workspace while "
        f"{doing}: the command {' '.join(failure.command)!r} {why}. A command "
        f"that failed has no output to read, and empty output from a broken "
        f"workspace is indistinguishable from empty output from a clean one - "
        f"so the phase fails here rather than being reported completed on a "
        f"verdict nobody actually got."
        + (f"\n  stderr: {stderr}" if stderr else "")
        + "\n  NOTHING WAS QUARANTINED: this phase's work is unverified and, if "
        "the workspace is already gone, unrecoverable."
    )


@dataclass(frozen=True)
class QuarantinedWork:
    """What one repository was holding when its phase ended, and where it went.

    ``pushed_ref`` is None when the quarantine push itself failed - the work is
    then genuinely gone, and saying so is the whole point of carrying the field.
    """

    repo: str
    branch: str
    commit_count: int
    files: tuple[str, ...]
    pushed_ref: str | None
    push_error: str | None = None


class UnpushedWorkQuarantinedError(Exception):
    """A phase ended holding work its workspace was about to destroy (#1184).

    THE FAILURE THIS EXISTS TO STOP. Every phase runs in an ephemeral workspace
    that is destroyed when the phase ends, and nothing checked that the phase
    had pushed - the instruction to push lived in a prompt, not in a gate. On
    PR #1072 the implement phase merged origin/main into its branch and the
    merge commit stayed local. The workspace was destroyed, the execution
    reported ``completed``, the PR head was unchanged, and hours later
    ``git merge-base --is-ancestor origin/main HEAD`` still exited 1: the merge
    simply never existed. It was caught a full run later, by chance.

    WHY QUARANTINE AND FAIL, rather than either half alone. Failing without
    saving would still LOSE the work - the workspace dies either way, and
    knowing about a loss is not preventing it. Pushing to the phase's own
    branch would save it but publish half-finished code onto a branch under
    review whenever a phase timed out mid-task. So the work is first pushed to
    a ref nobody reviews, unique to this phase run, and the phase then fails
    naming it - recoverable with one ``git fetch``, visible to no reviewer, and
    never reported as success.

    A phase that legitimately produces no commits - a bootstrap that only
    reports, a verify that only reads - never reaches here. Only work that
    would not survive the workspace is a failure.
    """

    def __init__(self, *, phase_id: str, quarantined: tuple[QuarantinedWork, ...]) -> None:
        self.phase_id = phase_id
        self.quarantined = quarantined
        super().__init__(_render_quarantine_report(phase_id, quarantined))


#: Enough of the file list to identify the work without burying the refs.
_MAX_FILES_REPORTED: Final[int] = 20


def _render_quarantine_report(phase_id: str, quarantined: tuple[QuarantinedWork, ...]) -> str:
    lines = [
        f"Phase '{phase_id}' ended holding work that its workspace would have "
        f"destroyed, so it failed instead of reporting completed:",
    ]
    for work in quarantined:
        lines.append(f"  {work.repo} (branch {work.branch}):")
        if work.commit_count:
            lines.append(f"    {work.commit_count} commit(s) on no remote")
        if work.files:
            shown = work.files[:_MAX_FILES_REPORTED]
            lines.extend(f"    uncommitted: {entry}" for entry in shown)
            if len(work.files) > len(shown):
                lines.append(f"    ... and {len(work.files) - len(shown)} more uncommitted")
        if work.pushed_ref is None:
            lines.append(f"    NOT RECOVERABLE: the quarantine push failed - {work.push_error}")
        else:
            lines.append(f"    quarantined at {work.pushed_ref}")
            lines.append(f"    recover with: git fetch origin {work.pushed_ref}")
    return "\n".join(lines)
