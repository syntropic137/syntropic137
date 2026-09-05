"""Error types for workflow execution (ISS-196).

Extracted from WorkflowExecutionEngine during M6 cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        PushedWork,
    )


def describe_exception(error: BaseException) -> str:
    """What to record about `error` when something has to be recorded.

    `str(error)` is the obvious answer and it is empty for any exception
    raised with no arguments - `TimeoutError()`, `CancelledError()`, a bare
    `Exception()`. The failure path then wrote "" into the session's
    `session_error` observation, and #1196's reproduction is exactly that: a
    failed phase whose only record of the failure said nothing at all.

    The class name is the one thing always available and it is genuinely
    diagnostic - "TimeoutError" points at the phase budget, "CancelledError"
    at a shutdown - so it is what an unnamed exception reports. Callers do not
    branch on which they got; that is the point.
    """
    return str(error).strip() or f"{type(error).__name__} (no message)"


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


class EmptyPhaseArtifactError(Exception):
    """A phase wrote its deliverable and the file had no content (#1195).

    THE FAILURE THIS EXISTS TO REPLACE. The empty content was refused by
    `CreateArtifactCommand`, correctly, and the refusal escaped as a raw
    Pydantic `ValidationError` - "String should have at least 1 character
    [type=string_too_short]" - which then failed the whole execution. That
    message describes a schema. An operator reading it at 2am has to work out
    that a nine-minute verify phase produced nothing storable, which phase it
    was, and whether anything survived. This says all three.

    Raised only after `recover_empty_artifact` has already declined, so
    reaching this means BOTH routes to the phase's conclusion were empty: the
    file it wrote and the last thing it said. That is a real "the agent
    produced nothing", and failing is right.

    THE THREE OUTCOMES ARE DELIBERATELY DISTINCT, because before #1195 two of
    them were the same opaque `failed`:

    - the phase wrote nothing collectable at all -> `PhaseProducedNoDeclaredOutputError`
    - it wrote an empty file and had said nothing -> this
    - it wrote an empty file but HAD said something -> no error; the phase
      completes on the recovered content, and the artifact says so in its title

    An operator distinguishes the first two by `phases[].error_message` and the
    third by following `phases[].artifact_id` to an artifact whose title
    carries `RECOVERED_TITLE_MARKER`.
    """

    def __init__(
        self,
        *,
        phase_id: str,
        phase_name: str,
        source_path: str,
    ) -> None:
        super().__init__(
            f"Phase '{phase_id}' ({phase_name}): THE ARTIFACT WAS EMPTY. It "
            f"wrote '{source_path}' and the file had no content, and nothing "
            f"could be recovered from the session transcript either - the "
            f"agent's last message was empty too. The phase's conclusion, if "
            f"it reached one, was not captured anywhere, so there is nothing "
            f"to store and the execution fails here."
        )
        self.phase_id = phase_id
        self.phase_name = phase_name
        self.source_path = source_path


@dataclass(frozen=True)
class FailedWorkspaceCommand:
    """The command that did not run, in enough detail to tell why."""

    command: tuple[str, ...]
    exit_code: int
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class QuarantinedWork:
    """What one repository was holding when its phase ended, and where it went.

    ``pushed_ref`` is None when the quarantine push itself failed - the work is
    then genuinely gone, and saying so is the whole point of carrying the field.

    A RECORD ANSWERS EXACTLY ONE of "where is it" and "why is it nowhere", and
    ``__post_init__`` rejects anything else. Not tidiness: every message in this
    module is a claim about whether an operator can fetch something back, and a
    record that answers both or neither would leave that claim to be guessed.
    Rejecting the shape at construction is what lets every reader below treat
    ``is_recoverable`` as a fact rather than an interpretation, and makes a
    third answer invented later fail here, loudly, instead of quietly picking
    whichever branch happened to be last.
    """

    repo: str
    branch: str
    commit_count: int
    files: tuple[str, ...]
    pushed_ref: str | None
    push_error: str | None = None

    def __post_init__(self) -> None:
        if (self.pushed_ref is None) == (self.push_error is None):
            raise ValueError(
                f"QuarantinedWork for {self.repo!r} must carry a pushed_ref or "
                f"a push_error, and exactly one of them: got "
                f"pushed_ref={self.pushed_ref!r}, push_error={self.push_error!r}. "
                f"A record saying neither where the work went nor why it went "
                f"nowhere makes every sentence printed about it a guess."
            )

    @property
    def is_recoverable(self) -> bool:
        """Whether a ref exists in the origin that an operator can actually fetch.

        THE ONE PLACE ``pushed_ref`` becomes a claim about durable state. Every
        headline in this module is derived from counting these, never from
        whether a list of records happened to be non-empty.
        """
        return self.pushed_ref is not None


#: Enough of the file list to identify the work without burying the refs.
_MAX_FILES_REPORTED: Final[int] = 20


def _by_durability(
    quarantined: tuple[QuarantinedWork, ...],
) -> tuple[tuple[QuarantinedWork, ...], tuple[QuarantinedWork, ...]]:
    """Split records into (a ref exists for it, the work is simply gone).

    THE SUBSTITUTION THIS EXISTS TO STOP. Both errors below used to choose what
    to say from whether their record list was EMPTY, which is a different
    question from whether anything survived - a list of three failed pushes is
    non-empty and not one byte of it can be fetched. That produced "SOME WORK
    WAS ALREADY QUARANTINED ... go and get them" four lines above the same
    message's own "NOT RECOVERABLE", with no ref in any origin. Counting is the
    fix, so headlines are chosen from these two sizes and nothing else.

    Saved first, because grouping puts the entries an operator can act on
    ahead of the ones they can only mourn, and makes the counts in the
    headline checkable against the list under it.
    """
    return (
        tuple(work for work in quarantined if work.is_recoverable),
        tuple(work for work in quarantined if not work.is_recoverable),
    )


def _repositories(count: int) -> str:
    """The count, said in English: '1 repository', '3 repositories'."""
    return f"{count} repository" if count == 1 else f"{count} repositories"


def _render_quarantined_work(work: QuarantinedWork) -> list[str]:
    """How one repository's quarantined work is described, wherever it appears.

    Shared by both errors that report quarantined work, so that neither can
    drift into calling a failed push recoverable: ``is_recoverable`` is read
    here and in the two summaries, all three off the same field, and the
    recovery line is only ever printed beside a ref that exists.
    """
    lines = [f"  {work.repo} (branch {work.branch}):"]
    if work.commit_count:
        lines.append(f"    {work.commit_count} commit(s) on no remote")
    if work.files:
        shown = work.files[:_MAX_FILES_REPORTED]
        lines.extend(f"    uncommitted: {entry}" for entry in shown)
        if len(work.files) > len(shown):
            lines.append(f"    ... and {len(work.files) - len(shown)} more uncommitted")
    if work.is_recoverable:
        lines.append(f"    quarantined at {work.pushed_ref}")
        lines.append(f"    recover with: git fetch origin {work.pushed_ref}")
    else:
        lines.append(f"    NOT RECOVERABLE: the quarantine push failed - {work.push_error}")
    return lines


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

    WHAT IT SAYS ABOUT WHAT SURVIVED, which is why it carries ``quarantined``.
    Repositories are inspected ONE AT A TIME, so a workspace holding several can
    have the first one's work already pushed to its quarantine ref by the time a
    command for the second fails. But being handed records is not the same as
    something having survived: a quarantine push can fail on its own, and the
    record it leaves behind names work that is gone. Both mistakes cost the
    work, in opposite directions - an operator told nothing was saved does not
    go looking for a ref that exists, and an operator told to go and get refs
    that were never written stops looking for the work anywhere else.

    So the message is chosen by COUNTING the records that carry a ref, over all
    four states that can produce: nothing reached, everything reached and lost,
    a mixture, everything reached and saved. Each says which of those it is and
    names the repositories, and none of them says "recoverable" without a ref
    to say it about.

    What it never claims either way is a verdict on the repositories it did not
    reach. Raising stops a false ``completed``; it cannot reach into a
    container that is already gone and make what was inside it durable.
    """

    def __init__(
        self,
        *,
        doing: str,
        failure: FailedWorkspaceCommand,
        quarantined: tuple[QuarantinedWork, ...] = (),
    ) -> None:
        self.doing = doing
        self.failure = failure
        #: Every repository the gate FINISHED with before the failure, whether
        #: or not its quarantine push landed. Empty means none were finished;
        #: it does NOT mean nothing survived, and non-empty does not mean
        #: anything did - only ``pushed_ref`` answers that, per record.
        self.quarantined = quarantined
        super().__init__(_render_inspection_failure(doing, failure, quarantined))

    @property
    def summary(self) -> str:
        """The same failure in one line, for a report that is about something else.

        The full message explains at length why silence cannot be read as a
        clean verdict, which is the right length when this error IS the
        failure. A caller that merely could not finish looking needs the fact
        and not the essay.
        """
        return f"{self.doing}: the command {' '.join(self.failure.command)!r} {_why(self.failure)}"


#: What is true of the walk so far, keyed by ``(a ref exists, a push failed)``.
#: A table rather than a chain of ``if``s because these four ARE the state
#: space and a reader can check them against each other in one place. The
#: defect this replaces was a single ``if not quarantined`` whose ``else``
#: covered three of these cells with a sentence true of only one of them.
#: Formatted with the counts, so the number an operator reads is the number of
#: refs that exist.
_INSPECTION_HEADLINE: Final[dict[tuple[bool, bool], str]] = {
    # 1. Nothing was finished before the failure - the ordinary case, and the
    #    case of a clean repository that needed no quarantining.
    (False, False): (
        "  NOTHING WAS QUARANTINED: this phase's work is unverified and, if "
        "the workspace is already gone, unrecoverable."
    ),
    # 2. Work was found and every push for it failed. Non-empty, and still
    #    nothing anyone can fetch.
    (False, True): (
        "  NOTHING WAS QUARANTINED: work was found in {lost} before this "
        "command failed, and every quarantine push for it failed too, so no "
        "refs/syn/lost ref exists. What follows names what was lost - it does "
        "not offer it back:"
    ),
    # 3. A mixture. The counts are the point: they say how much of the list
    #    below is actually being offered back.
    (True, True): (
        "  PART OF THIS PHASE'S WORK WAS QUARANTINED before this command "
        "failed: a ref exists for {saved} and not for {lost}. Only the entries "
        "below that name a ref can be fetched back:"
    ),
    # 4. Everything the gate finished with is durable.
    (True, False): (
        "  SOME WORK WAS ALREADY QUARANTINED before this command failed. "
        "Repositories are inspected one at a time, and the gate finished "
        "{saved} before it stopped - go and get them:"
    ),
}

#: Said after the detail lines in every case that HAS detail lines: the
#: repositories the gate never reached are not covered by any of the four.
_REST_IS_UNVERIFIED: Final[str] = (
    "  Every repository after those is unverified and, if the workspace is "
    "already gone, unrecoverable."
)


def _why(failure: FailedWorkspaceCommand) -> str:
    """Why a command produced no answer, said the same way wherever it is said."""
    return "timed out, so it did not finish" if failure.timed_out else f"exited {failure.exit_code}"


def _render_inspection_failure(
    doing: str,
    failure: FailedWorkspaceCommand,
    quarantined: tuple[QuarantinedWork, ...],
) -> str:
    why = _why(failure)
    stderr = failure.stderr.strip()
    lines = [
        f"The unpushed-work gate could not verify this phase's workspace while "
        f"{doing}: the command {' '.join(failure.command)!r} {why}. A command "
        f"that failed has no output to read, and empty output from a broken "
        f"workspace is indistinguishable from empty output from a clean one - "
        f"so the phase fails here rather than being reported completed on a "
        f"verdict nobody actually got."
    ]
    if stderr:
        lines.append(f"  stderr: {stderr}")
    saved, lost = _by_durability(quarantined)
    lines.append(
        _INSPECTION_HEADLINE[bool(saved), bool(lost)].format(
            saved=_repositories(len(saved)), lost=_repositories(len(lost))
        )
    )
    detail = [line for work in (*saved, *lost) for line in _render_quarantined_work(work)]
    if detail:
        lines.extend(detail)
        lines.append(_REST_IS_UNVERIFIED)
    return "\n".join(lines)


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

    THE PUSH CAN ALSO FAIL, so "quarantined" in the name is what was attempted,
    not what is promised. The report ends by counting the refs that exist and
    saying whether all, some or none of the work above can be fetched back,
    from the same count the other error uses. A reader must not have to add up
    the per-repository lines themselves to learn whether anything survived.

    A phase that legitimately produces no commits - a bootstrap that only
    reports, a verify that only reads - never reaches here. Only work that
    would not survive the workspace is a failure.
    """

    def __init__(self, *, phase_id: str, quarantined: tuple[QuarantinedWork, ...]) -> None:
        self.phase_id = phase_id
        self.quarantined = quarantined
        super().__init__(_render_quarantine_report(phase_id, quarantined))


#: How much of the work above can be fetched back, keyed exactly as
#: ``_INSPECTION_HEADLINE`` is. There is deliberately no ``(False, False)``
#: entry: an error reporting no work at all is rejected in
#: ``_render_quarantine_report``, because no sentence here would be true of it.
_QUARANTINE_SUMMARY: Final[dict[tuple[bool, bool], str]] = {
    (False, True): (
        "  NONE OF IT IS RECOVERABLE: every quarantine push failed, so there "
        "is no refs/syn/lost ref to fetch for any of the work above."
    ),
    (True, True): (
        "  PARTLY RECOVERABLE: a ref exists for {saved} and not for {lost} - "
        "only the entries above that name a ref can be fetched back."
    ),
    (True, False): ("  All of it is recoverable: a ref exists for {saved}, named above."),
}


def _render_quarantine_report(phase_id: str, quarantined: tuple[QuarantinedWork, ...]) -> str:
    if not quarantined:
        raise ValueError(
            f"UnpushedWorkQuarantinedError for phase {phase_id!r} was built with "
            f"no quarantined work. The gate raises it only after finding work, "
            f"so an empty one is a caller bug rather than a phase that failed, "
            f"and there is no true report to print for it."
        )
    saved, lost = _by_durability(quarantined)
    lines = [
        f"Phase '{phase_id}' ended holding work that its workspace would have "
        f"destroyed, so it failed instead of reporting completed:",
    ]
    lines.extend(line for work in (*saved, *lost) for line in _render_quarantined_work(work))
    lines.append(
        _QUARANTINE_SUMMARY[bool(saved), bool(lost)].format(
            saved=_repositories(len(saved)), lost=_repositories(len(lost))
        )
    )
    return "\n".join(lines)


@dataclass(frozen=True)
class StrandedWork:
    """Where a FAILED phase's work already is, when nothing else will say (#1200).

    THE MIRROR OF `QuarantinedWork`, and deliberately shaped like it. #1184
    covers the phase that ended holding work nobody had pushed: it saves that
    work to a ref and fails naming it. This covers the phase that DID push and
    then failed anyway - most often on the #1167 output-artifact contract,
    which is unmet the moment the phase writes no deliverable, however good the
    code it pushed. The commits are already durable and already on a branch;
    the only thing missing is anyone being told. It happened three times in one
    day, and twice a human found the branch by hand and opened the PR - both
    merged, so the work was never the problem.

    NOTHING HERE PUSHES, QUARANTINES OR PUBLISHES. Opening the PR on the
    author's behalf is a different decision (#1197), and pushing on its behalf
    would risk overwriting a remote nobody inspected. Saying where the work is
    costs nothing and cannot be wrong in that direction.

    THE CLAIM IS COUNTED, NEVER ASSUMED. `pushed` holds one record per
    repository where a commit THIS PHASE PRODUCED was confirmed to be on a
    remote, so "is any of this recoverable" is the size of that tuple - never
    the truthiness of a branch name that may never have left the workspace.
    That substitution is the exact defect #1184 needed four review passes to
    remove from its own reporting.

    "THIS PHASE PRODUCED" IS ALSO COUNTED, and it is the second half of the
    same discipline. A phase inherits a branch that is already pushed, so "the
    workspace's HEAD is on a remote" is true of a phase that did nothing at
    all, and reporting it made "pushed work, wrote no deliverable" and
    "produced nothing" the same record - a recoverable incident wearing the
    unrecoverable one's clothes again, one field further along. Only commits
    absent from the workspace when the phase started are eligible; see
    `PhaseStartingPoint`.

    `unreadable` says why the inspection stopped early, and exists so that an
    answer nobody obtained can never be printed as an answer of "nothing". The
    two are kept apart the whole way to the API; see `confirmed_locations`.
    """

    pushed: tuple[PushedWork, ...]
    unreadable: str | None = None

    @property
    def confirmed_locations(self) -> tuple[PushedWork, ...] | None:
        """What an API client is told, in the one place that decides it.

        THREE-VALUED, in the shape this codebase already uses for
        `agent_session_ids` (#1176): records are what was found, `()` means the
        inspection FINISHED and nothing in this workspace was on any remote,
        and `None` means nothing could tell us. Collapsing the last two would
        report a phase whose workspace had already died as one that verifiably
        pushed nothing - the recoverable incident wearing the unrecoverable
        one's clothes, which is the whole failure this module exists to stop.

        Records survive an incomplete inspection because each one is a fact
        about a ref that exists; not finishing does not unmake them.
        """
        if self.pushed:
            return self.pushed
        return None if self.unreadable else ()


#: What is true of a failed phase's work, keyed by ``(something is on a remote,
#: the inspection stopped early)``. A table for the same reason
#: ``_INSPECTION_HEADLINE`` is one: these four ARE the state space, and a reader
#: checking them against each other should not have to reconstruct them from a
#: chain of ``if``s. Formatted with the count of repositories a ref was found
#: for, so the number read is the number of places to look.
_STRANDED_HEADLINE: Final[dict[tuple[bool, bool], str]] = {
    # 1. The ordinary failure: nothing was pushed and nothing is claimed.
    (False, False): (
        "  NOTHING OF THIS PHASE'S WORK IS ON A REMOTE: it advanced no branch "
        "onto one, so there is no branch to open a PR from and nothing of its "
        "own to fetch back. If it committed anything, the workspace took it. "
        "This says nothing about commits that were already there when the "
        "phase started - those are not its work and not what is being offered."
    ),
    # 2. The inspection could not finish and found nothing before it stopped.
    #    NOT the same as (1) and never merged with it: this says nobody looked.
    (False, True): (
        "  WHERE THIS PHASE'S WORK WENT IS UNKNOWN: the workspace stopped "
        "answering before anything was found ({unreadable}), so this is not a "
        "report that nothing was pushed - it is the absence of a report. Check "
        "the remote for a branch from this execution before assuming either."
    ),
    # 3. Found something, then stopped. The records below are still true.
    (True, True): (
        "  PART OF THIS PHASE'S WORK IS ON A REMOTE - a branch exists for "
        "{found} - and the inspection then stopped ({unreadable}), so there "
        "may be more it never reached. What it did confirm:"
    ),
    # 4. The incident this exists for: the work is fine, and nothing said so.
    (True, False): (
        "  THIS PHASE'S WORK IS ON A REMOTE. It pushed {found} and then failed "
        "before anything opened a PR for it, so the commits below are complete "
        "and unreferenced. Nothing was pushed or published on its behalf:"
    ),
}


def _render_pushed_work(work: PushedWork) -> list[str]:
    """How one repository's pushed work is described.

    Deliberately the same shape as `_render_quarantined_work`: an operator
    reading a failed execution should not have to learn two layouts to answer
    the one question both errors are about.
    """
    return [
        f"  {work.repo} (branch {work.branch}):",
        f"    pushed at {work.commit}",
        f"    look at it with: git fetch origin {work.branch} && git checkout {work.commit}",
    ]


def describe_stranded_work(work: StrandedWork) -> str:
    """Say where a failed phase's work went, in the words an operator reads.

    Appended to the failure's own message rather than replacing it: WHY the
    phase failed and WHERE its work is are different questions, and #1167's
    answer to the first must stay exactly as loud as it is.
    """
    lines = [
        _STRANDED_HEADLINE[bool(work.pushed), bool(work.unreadable)].format(
            found=_repositories(len(work.pushed)), unreadable=work.unreadable
        )
    ]
    lines.extend(line for record in work.pushed for line in _render_pushed_work(record))
    return "\n".join(lines)
