"""What a phase's workspace is holding that its teardown would erase.

THE GATE (#1184). Every phase runs in an ephemeral workspace that is destroyed
when the phase ends. Until this gate existed, nothing checked that the phase had
pushed: the instruction lived in a prompt, and a phase that committed without
pushing still reported ``completed`` while its commits went into the bin with
the container.

`refuse_to_complete_unsaved_phase` is called once per phase, immediately before
the phase is declared complete and while the workspace - and the git credential
the setup phase deliberately leaves in place - is still alive. It answers one
question, "would anything in this workspace fail to survive it", and if so puts
that work somewhere durable before raising. Callers need nothing but that: no
git, no ref naming, no knowledge of how many repositories a workspace holds.

THE SECOND CALLER ASKS THE SAME QUESTION ON THE PATHS THAT NEVER REACH THE GATE
(#1231). `save_unpushed_work` runs the gate's walk for a phase killed at its
``timeout_seconds`` and for an execution the user cancelled, and reports what it
saved as a value instead of a refusal, because those have already failed for a
reason of their own and must keep it. It is the gate called and caught rather
than a walk that resembles one: two implementations of "what would be lost" is
exactly the drift this file is one module to avoid.

WHERE THE COMMANDS GO. Every command here is issued through `workspace_git`,
which bounds it, turns hooks off, and refuses to let a command that did not
answer be read as one that answered "clean". That module's docstring is where
the reasoning for all three lives; `branch_observation`, which asks the
opposite question in the same window, goes through the same door.

WHAT COUNTS AS WORK IS WHAT THE PHASE COULD DO, NOT WHAT IT SAID (#1308). Git
records who wrote a file and nothing else: a half-finished feature and a
``Cargo.lock`` that ``cargo check`` rewrote while merely inspecting the
toolchain arrive here as the same single line of ``status --porcelain``.
Reading that line as work failed a bootstrap phase that had done its job
correctly, quarantined the lockfile churn, and threw away an hour of
already-pushed work behind it.

There is no reading of the diff that fixes this, and a rule about filenames
would be a guess in both directions - lockfile churn IS the deliverable of a
dependency-bump phase, and a tool can dirty anything.

ASKING THE PHASE DOES NOT FIX IT EITHER, which is the correction #1317 needed.
``delivers_repo_changes`` is declared in the workflow definition, beside
``clone_repos`` and ``can_open_pr``, where the agent cannot decline it - but
it states what a phase INTENDS, and the gate needs to know what it CAN do.
Every phase that declares False still holds ``Bash`` or ``Write``, so a gate
that believed the declaration threw away an agent's genuine edit in precisely
the case it was built for. An intention is not a guarantee and cannot be
spent as one.

SO THE EXEMPTION IS EARNED FROM THE WORKSPACE, NOT ASSERTED BY THE PHASE. A
dirty path stops counting as work only when BOTH hold: the phase declared the
churn is not its deliverable, AND the repository sits on a read-only mount, so
the agent could not have authored anything in it. The second half is read out
of ``/proc/self/mountinfo`` - the kernel's own account, which an agent holding
an empty capability set can neither remount nor forge, and which the
permission bits are not, since the agent OWNS this tree and may chmod it back
at will. With the second half missing the gate is exactly what #1184 built.

NOTHING MOUNTS THEM READ-ONLY YET, so #1308's incident still fails its phase
and this is the honest state of it: the loss the exemption would have caused
is worse than the failure it would have prevented. The remaining half belongs
to provisioning - repositories cloned outside the agent-writable mount and
bound back in read-only, build caches and output somewhere writable,
dependency commands run frozen - and it cannot be done from inside the
workspace at all, so it lands with the container's creation, in
agentic-primitives and the image, not here. This gate needs no change when it
does: `_write_protected` simply starts finding repositories.

A COMMIT IS AN AUTHORING ACT AND IS ALWAYS WORK. No build tool writes one, so
``delivers_repo_changes`` does not reach unpushed commits at all: a phase that
declares False and commits anyway still fails, still quarantines, and still
says where the work went. What the declaration decides is narrower - whether an
UNCOMMITTED change, by itself, is evidence of anything. False does not exempt a
path and does not make the files invisible: when a phase holds commits too, the
quarantine still captures the whole working tree, because by then the phase has
demonstrably authored something and every byte beside it is worth keeping.

SCOPE is `workspace_git.repositories`': what it finds is what this gate judges,
and a submodule's own objects are outside it.
"""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    CredentialRenewalFailedError,
    QuarantinedWork,
    QuarantinePathUnusableError,
    SavedWork,
    UnpushedWorkQuarantinedError,
    WorkspaceInspectionFailedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
    BOUND_FIRED_EXIT_CODE,
    GitWorkspace,
    answered,
    checked,
    git,
    push,
    repositories,
    run_bounded,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoItem

logger = logging.getLogger(__name__)

#: The kernel's own account of what is mounted where, and the only evidence
#: here an agent cannot manufacture: writing it needs a mount, mounting needs
#: CAP_SYS_ADMIN, and a workspace agent has no capabilities at all. Preferred
#: over `mount` and `findmnt`, neither of which the image promises to ship.
_MOUNT_TABLE: Final[str] = "/proc/self/mountinfo"

#: The mount option that means the filesystem refuses every write, whatever
#: the permission bits underneath it say.
_READ_ONLY_OPTION: Final[str] = "ro"

#: mountinfo's fixed prefix: id, parent, dev, root, mount point, options. Any
#: line shorter than this is not one of its records.
_MOUNT_FIELDS: Final[int] = 6

#: Namespace for quarantined work. Deliberately outside refs/heads and
#: refs/tags: nothing fetches it by default, no PR shows it, and no reviewer is
#: ever shown it. It exists to be recovered on purpose, by someone who was told
#: the name.
_QUARANTINE_NAMESPACE: Final[str] = "refs/syn/lost"

#: The quarantine commit is written through a scratch index so the doomed
#: worktree's own index is never touched. Starting from an empty file also
#: means the tree is the WORKTREE as it stands rather than whatever happened to
#: be staged - at the cost of re-hashing every tracked file, which is
#: acceptable on a path that only runs when a phase is already failing.
_SCRATCH_INDEX: Final[str] = "/tmp/syn-quarantine.index"

#: How long the rescue push may go on being waited for AFTER the phase has
#: been cancelled (#1396). A cancellation is a request to stop, so the salvage
#: cannot simply ignore it: what it buys is the few seconds the push needs to
#: finish, and then the cancellation is re-applied whatever the answer was.
#: Generous against `REMOTE_TIMEOUT_SECONDS`, which is the bound already in the
#: push's own argv, so in the ordinary case THAT one fires first and this is
#: the backstop for a workspace backend that never returns at all.
#:
#: A module global read at call time, like the bounds in `workspace_git`, so a
#: test can lower it and make the backstop fire in a second.
_CANCELLED_PUSH_SECONDS: Final[float] = 30.0

#: How many times the phase-start rehearsal tries something that talks to
#: GitHub before it reads a failure as this phase's verdict (#1396). Minting a
#: token and a dry-run push are both one request to a third party, and a
#: timeout, a 5xx or a secondary rate limit are momentary - refusing an
#: execution for one throws away a phase that would have run perfectly.
_RENEWAL_ATTEMPTS: Final[int] = 3

#: The wait between those attempts. Long enough to outlive a blip, short
#: enough that the whole rehearsal stays a few seconds of phase start.
#:
#: Module globals, read at call time like the bounds in `workspace_git`, so a
#: test can make the retries instant.
_RENEWAL_RETRY_SECONDS: Final[float] = 2.0


async def rehearse_quarantine_credential(
    workspace: GitWorkspace, *, execution_id: str, phase_id: str
) -> None:
    """Prove this phase HAS a credential that reaches origin, before it runs (#1393).

    THE NET IS OTHERWISE UNTESTABLE UNTIL THE FALL. Everything below runs
    exactly once per phase, at teardown, on a phase that has already failed -
    so a workspace that holds no usable credential at all, or that cannot
    reach ``origin``, is invisible right up to the moment a commit and nine
    modified files are riding on it. `exec-db6f687e991a` is what that costs.

    So the same push is made here with ``--dry-run``: same `push`, same argv,
    same ``origin``, same ``refs/syn/lost`` ref this phase would really use,
    and the credential renewed first exactly as the real one renews it.

    WHAT THAT DOES AND DOES NOT ESTABLISH, stated narrowly on purpose (#1396).
    git connects, authenticates, and negotiates - so a missing or unusable
    credential, a remote that is not there, and a transport that will not
    answer are all found here, and those are the failures this function is
    named for. What ``--dry-run`` never does is run ``git-receive-pack``'s
    update phase: no ``pre-receive`` hook fires, no ruleset is consulted, no
    ref is locked. A remote that accepts the connection and then declines the
    ref update passes this rehearsal and refuses the real push, and that is
    demonstrated, not assumed - see
    `test_a_rehearsal_that_passed_is_no_promise_that_the_server_will_accept`.

    So this is a CREDENTIAL AND CONNECTIVITY rehearsal and is not evidence
    that the quarantine push will be accepted. The stronger claim would need a
    real ref created on the remote and then deleted, which spends a write on
    every phase start to test a path almost none of them take; the modest
    claim that is actually true is worth more than an over-claiming one,
    because the only thing worse than an untested net is a net reported as
    tested. The remaining exposure is covered where it lands: a refused
    quarantine push at teardown still reports ``pushed_ref=None`` with the
    remote's own words and prints NOT RECOVERABLE.

    RAISES RATHER THAN WARNS, which is the deliberate part. A logged warning
    at phase start is read by nobody until someone is already looking for why
    work vanished, which is the position #1393 was reported from. Raising ends
    the phase before its agent has been given anything to lose: the cost is the
    provisioning already spent, against an hour of agent time handed to a
    workspace that has just shown it cannot give the work back.

    A repository with no commits yet is skipped - there is nothing to name as
    the source of a push, and a phase that later commits into it is covered by
    every other repository's rehearsal.

    A MINT THAT FAILED IS NOT A VERDICT ABOUT THIS PHASE (#1396). Failing here
    on the renewal alone refused phases whose workspace was holding a
    credential that worked: the setup phase installed one minutes ago, it has
    most of its hour left, and a rate limit or a five-second network fault
    between here and GitHub says nothing about it. So the renewal is retried a
    bounded number of times, and if it still cannot happen the credential
    already in the container is KEPT and the rehearsal below is run with it.
    The rehearsal is the only thing that can produce a verdict, because it is
    the only thing that spends the credential on the actual remote.

    AND NEITHER IS SILENCE, which is the same argument one layer out (#1396).
    The rehearsal used to refuse on the third non-zero push for no reason but
    that it was the third: a persistent timeout and a real refusal ended the
    phase identically, so an origin that had said NOTHING was read as an
    origin that had said no. A rehearsal whose whole promise is "credential
    and connectivity" cannot spend the absence of connectivity as evidence
    about the credential. So the outcome is CLASSIFIED rather than counted -
    `workspace_git.answered` - and only a push that came back refuses the
    phase. One that never came back logs a warning and lets the phase run; the
    exposure that leaves is the one this rehearsal never covered anyway, and
    it still lands where every uncovered case lands, on a teardown push that
    fails and reports NOT RECOVERABLE.

    THE CLASSIFICATION IS COARSER THAN THE RULE, and the gap is stated rather
    than hidden. "Refuse only on an authorization or policy rejection" would
    need an answered failure to be separable into "origin refused you" and
    "the network broke after origin answered". git does not expose that: on
    the image's git 2.39.5 a DNS failure, a refused connection and an HTTP
    401, 403, 500 or 502 all exit 128 with byte-identical trace2 structure,
    differing only in the prose of the message, and classifying on prose is a
    rule that git's next release may silently rewrite. So an answered failure
    refuses, which is the conservative half: the failure class this guard was
    built for - the expired credential of #1393 - stays caught, and the class
    it cannot yet separate stays with it rather than being waved through on a
    guess.

    Raises:
        QuarantinePathUnusableError: origin ANSWERED a rehearsal push with a
            refusal, after bounded retries. Neither a renewal that failed nor
            an origin that never answered reaches here.
        WorkspaceInspectionFailedError: the workspace would not answer, so
            nothing was rehearsed and no verdict exists. Propagated rather
            than downgraded, for the reason every command in this module is
            checked: "I could not look" must never be spent as "I looked and
            it was fine".
    """
    repos = await repositories(workspace)
    if not repos:
        return
    await _renew_for_the_rehearsal(workspace, phase_id=phase_id)

    ref = _quarantine_ref(execution_id, phase_id)
    unanswered: list[str] = []
    for repo in repos:
        head = (await git(workspace, repo, "rev-parse", "--revs-only", "HEAD")).strip()
        if not head:
            continue
        rehearsed = await _rehearsal_push(workspace, repo, commit=head, ref=ref)
        if rehearsed.exit_code == 0:
            continue
        if not answered(rehearsed):
            # SILENCE IS NOT A VERDICT (#1396). Nothing came back within the
            # bound, so origin has said nothing about this credential - and a
            # rehearsal that promises "credential and connectivity" has no
            # business converting the absence of connectivity into a refusal.
            # The walk continues rather than returning, because these origins
            # are per-repository and a later one may still answer with a real
            # refusal, which IS a verdict and must still be acted on.
            unanswered.append(repo)
            continue
        raise QuarantinePathUnusableError(
            phase_id=phase_id,
            detail=(
                f"A rehearsal push of {repo} to {ref} was refused by origin: "
                f"{(rehearsed.stderr or rehearsed.stdout).strip() or 'no output'}"
            ),
        )
    if unanswered:
        logger.warning(
            "Phase %s is starting UNREHEARSED: origin never answered a rehearsal push "
            "of %s within the bound, after %d attempts, so nothing is known about the "
            "credential this workspace holds. The phase runs because an origin that "
            "cannot be reached now says nothing about whether it can be reached in an "
            "hour; if it still cannot be, a quarantine push at teardown will fail and "
            "that phase's work will be reported NOT RECOVERABLE (#1396).",
            phase_id,
            ", ".join(unanswered),
            _RENEWAL_ATTEMPTS,
        )
        return
    logger.info(
        "Phase %s holds a credential that reaches origin, so a quarantine push to %s "
        "would be attempted with one. Server-side acceptance of that ref is NOT "
        "covered by this rehearsal (#1396).",
        phase_id,
        ref,
    )


async def _renew_for_the_rehearsal(workspace: GitWorkspace, *, phase_id: str) -> None:
    """Mint a fresh credential if it can be minted, and never fail the phase for it.

    RETRIED, because the failures this call has are mostly not about this
    phase: minting a GitHub installation token is one HTTPS request to a
    third party, and a timeout, a 5xx or a secondary rate limit are all
    momentary and all arrive here indistinguishable from a permanent refusal.
    `_RENEWAL_ATTEMPTS` of them, `_RENEWAL_RETRY_SECONDS` apart, costs seconds
    at phase start and converts the most common transient failure into no
    failure at all.

    AND THEN NOT FATAL EITHER. What the workspace holds after all the attempts
    have failed is the credential the setup phase installed, which is minutes
    old and good for an hour - the same credential this phase would have
    spent anyway had the renewal never been attempted. Refusing the phase at
    that point throws away an execution that could have run, to protect work
    it has not been given yet, on the strength of evidence about GitHub's
    availability rather than about this workspace. The rehearsal that follows
    asks the question that actually matters, with the credential that is
    actually there.

    `asyncio.CancelledError` is re-raised rather than retried: nothing has
    been given to this phase yet, so there is nothing here to salvage, and
    the teardown path's argument for pushing anyway does not apply.
    """
    for attempt in range(1, _RENEWAL_ATTEMPTS + 1):
        try:
            await workspace.renew_git_credential()
            return
        except asyncio.CancelledError:
            raise
        except Exception as unrenewable:
            # ANY exception, for the same reason the teardown caller swallows
            # any: the protocol names one type, and a policy that only applied
            # to that one would be conditional on every workspace keeping its
            # half of it.
            if attempt < _RENEWAL_ATTEMPTS:
                logger.info(
                    "Could not mint a fresh git credential for phase %s (attempt %d of "
                    "%d): %s. Retrying in %.0fs.",
                    phase_id,
                    attempt,
                    _RENEWAL_ATTEMPTS,
                    unrenewable,
                    _RENEWAL_RETRY_SECONDS,
                )
                await asyncio.sleep(_RENEWAL_RETRY_SECONDS)
                continue
            logger.warning(
                "Could not mint a fresh git credential for phase %s after %d attempts: "
                "%s. KEEPING the credential this workspace was provisioned with, which "
                "is minutes old, and rehearsing the quarantine push with it: whether "
                "THAT works is the only thing that decides this phase (#1396).",
                phase_id,
                _RENEWAL_ATTEMPTS,
                unrenewable,
            )
    return


async def _rehearsal_push(
    workspace: GitWorkspace, repo: str, *, commit: str, ref: str
) -> ExecutionResult:
    """The rehearsal's dry run, retried so a blip cannot refuse a viable phase.

    The same bound and the same reasoning as the renewal above, one layer
    further out: this push IS the verdict, so a network fault that made it
    fail once would take a whole execution off the board.

    RETURNS THE LAST RESULT, AND DOES NOT JUDGE IT. Every non-zero outcome is
    retried, including one that looks definitive, because "definitive" here is
    read from an exit code that a momentarily broken remote also produces -
    `test_a_rehearsal_push_that_fails_transiently_is_retried_before_it_is_fatal`
    is a remote that is gone for one push and back for the next, and exits 128
    exactly as a real refusal does. What the retries establish is therefore
    only PERSISTENCE, never the kind of failure; the caller classifies what
    survives them, and this function must not pre-empt that by deciding a
    failure is final (#1396).

    THE BOUND IS WHAT STOPS THIS DELAYING A PHASE START INDEFINITELY, and it
    is two bounds multiplied rather than one: at most `_RENEWAL_ATTEMPTS`
    pushes, each cut off by `workspace_git.REMOTE_TIMEOUT_SECONDS`, with
    `_RENEWAL_RETRY_SECONDS` between them. An origin that accepts connections
    and then says nothing - the worst case, because it is the one with no
    error to return early on - costs that product and then lets the phase
    start.
    """
    for attempt in range(1, _RENEWAL_ATTEMPTS + 1):
        rehearsed = await push(workspace, repo, commit=commit, ref=ref, dry_run=True)
        if rehearsed.exit_code == 0 or attempt == _RENEWAL_ATTEMPTS:
            return rehearsed
        logger.info(
            "A rehearsal push of %s to %s failed (attempt %d of %d): %s. Retrying in "
            "%.0fs, because one failure establishes nothing about this phase.",
            repo,
            ref,
            attempt,
            _RENEWAL_ATTEMPTS,
            (rehearsed.stderr or rehearsed.stdout).strip() or "no output",
            _RENEWAL_RETRY_SECONDS,
        )
        await asyncio.sleep(_RENEWAL_RETRY_SECONDS)
    raise AssertionError("unreachable: the loop returns on its last attempt")


async def refuse_to_complete_unsaved_phase(
    workspaces: Mapping[str, GitWorkspace],
    todo: TodoItem,
    *,
    delivers_repo_changes: bool,
) -> None:
    """Refuse to complete a phase that is holding work its teardown would erase.

    MUST be called before the aggregate is told the phase completed and before
    the phase's workspace context manager is exited. That window is the whole
    point: it is the last moment at which the work still exists to be saved,
    and the last at which refusing leaves the phase indistinguishable, to every
    path downstream, from any other phase failure (#1184). Called after either,
    the guard can still detect the loss but can no longer prevent it.

    The caller hands over the live workspace map, the to-do item and the
    completing phase's own declaration, and needs to know nothing else - which
    workspace belongs to the phase, and what an absent one means, are decided
    here. ABSENCE IS NOT A FAILURE, and that is a verdict rather than an
    oversight: a phase with no workspace is holding nothing that dying could
    erase, so there is nothing to save and nothing to refuse. Contrast a
    workspace that is present but will not answer, which
    `quarantine_unpushed_work` treats as the failure it is.

    Args:
        workspaces: Live workspaces, by phase id.
        todo: The COMPLETE_PHASE item naming the phase at stake.
        delivers_repo_changes: What that phase's definition declares about
            repository changes. Required rather than defaulted, because a hop
            that forgot it would silently restore #1308. Necessary for the
            exemption and not sufficient for it: what the phase was ABLE to
            write is established here, from the workspace.

    Raises:
        UnpushedWorkQuarantinedError: as `quarantine_unpushed_work`.
        WorkspaceInspectionFailedError: as `quarantine_unpushed_work`.
    """
    phase_id = todo.phase_id
    workspace = workspaces.get(phase_id) if phase_id is not None else None
    if phase_id is None or workspace is None:
        return
    await quarantine_unpushed_work(
        workspace,
        execution_id=todo.execution_id,
        phase_id=phase_id,
        delivers_repo_changes=delivers_repo_changes,
    )


async def quarantine_unpushed_work(
    workspace: GitWorkspace,
    *,
    execution_id: str,
    phase_id: str,
    delivers_repo_changes: bool,
) -> None:
    """Fail the phase if it is holding work the workspace's death would erase.

    Returns silently when every repository is clean and fully pushed - which is
    the normal case, and includes the phase that legitimately produced nothing
    at all (a bootstrap that only reports, a verify that only reads). Silence
    here means "nothing is being lost", and - because every command it relies
    on is checked - never "nothing was checked".

    ``delivers_repo_changes`` NARROWS what "nothing" can mean for this phase;
    it does not decide it (#1308). With it False, a dirty tree is silence only
    in a repository this workspace mounted read-only, where the phase could
    not have authored the change whatever it intended. Everywhere else - which
    is everywhere, until provisioning mounts them read-only - a dirty tree is
    work, exactly as it was before the declaration existed. Unpushed commits
    are work under every combination of the two. See the module docstring for
    why an intention cannot be spent as a guarantee.

    Raises:
        UnpushedWorkQuarantinedError: work was found. It has already been
            pushed to ``refs/syn/lost/<execution-id>/<phase-id>`` in each
            affected repository, and the error names those refs.
        WorkspaceInspectionFailedError: a command this gate depends on did not
            run, so there is no verdict to give for the repositories it had
            not reached yet. Every repository it HAD finished with is named in
            the error, each said to be recoverable or not according to whether
            its push landed: work saved before the failure is not unsaved by
            it, and work whose push failed is not saved by being listed.
    """
    ref = _quarantine_ref(execution_id, phase_id)
    quarantined: list[QuarantinedWork] = []
    try:
        repos = await repositories(workspace)
        # BOTH HALVES, OR NEITHER (#1308). The declaration is asked first only
        # because it is free: a phase that delivers repository changes is
        # judged strictly whatever it was mounted on, and never pays for the
        # mount table. A phase that disclaims them still has to be shown
        # incapable, repository by repository.
        protected = (
            frozenset() if delivers_repo_changes else await _write_protected(workspace, repos)
        )
        for repo in repos:
            work = await _unsaved_work(workspace, repo, uncommitted_is_work=repo not in protected)
            if work is not None:
                record, cancellation = await _quarantine(workspace, repo, work, ref=ref)
                quarantined.append(record)
                if cancellation is not None:
                    # SAID OUT LOUD BEFORE IT IS RE-APPLIED, because re-raising
                    # is the end of this walk: the repositories after this one
                    # are not visited, and the error that would have named the
                    # refs is never built. What was pushed still exists, and an
                    # operator who only sees "cancelled" has no way to know it
                    # (#1396).
                    logger.warning(
                        "This phase was cancelled while its work was being rescued. The "
                        "push for %s was completed anyway and %s. Repositories after it "
                        "were not reached. Re-applying the cancellation now.",
                        repo,
                        f"landed at {ref}"
                        if record.pushed_ref
                        else f"was refused ({record.push_error}), so that work is NOT RECOVERABLE",
                    )
                    raise cancellation
    except WorkspaceInspectionFailedError as unreadable:
        # PARTIAL PROGRESS IS STILL PROGRESS, and this loop is the only place
        # that knows there was any. Repositories are done ONE AT A TIME, so by
        # the time the third one stops answering, the first two's quarantine
        # refs have already been pushed and are durable in their origins.
        # Re-raised carrying them because the bare "NOTHING WAS QUARANTINED"
        # the error would otherwise print is, in that case, false in the one
        # direction that costs the work: an operator told nothing was saved
        # does not go looking for a ref that exists. That is #1184 itself -
        # a confident statement nobody checked - pointing the other way.
        #
        # HANDED OVER UNFILTERED, including the records whose push failed.
        # Those name work that is gone, and dropping them would hide a loss;
        # keeping them is only safe because the error counts pushed_ref rather
        # than records, so a list of failed pushes cannot become a claim that
        # something survived. Empty when the first repository is the one that
        # failed, or when everything before it was clean.
        raise WorkspaceInspectionFailedError(
            doing=unreadable.doing,
            failure=unreadable.failure,
            quarantined=tuple(quarantined),
        ) from unreadable
    if quarantined:
        raise UnpushedWorkQuarantinedError(phase_id=phase_id, quarantined=tuple(quarantined))


async def save_unpushed_work(
    workspace: GitWorkspace,
    *,
    execution_id: str,
    phase_id: str,
    delivers_repo_changes: bool,
) -> SavedWork:
    """Empty a DYING workspace of everything no remote has, and say where it went.

    THE SAME WALK THE COMPLETION GATE RUNS, on the paths that never reach it
    (#1231). A phase killed at its ``timeout_seconds`` exits 124, which
    `_handle_run_agent` turns into a raise, so it unwinds to the failure path
    and never to `refuse_to_complete_unsaved_phase` - and the failure path only
    ever LOOKED. `exec-9cb32b4bbfe7` held two commits that existed, were
    reported accurately, and were then deleted with the container.

    LITERALLY THE GATE, called and caught, rather than a second walk that
    resembles it. The two paths must not be able to disagree about what counts
    as unsaved, which ref the work goes to, or whether a push landed, and the
    cheapest way to guarantee that is one implementation and no copy. That is
    also why ``delivers_repo_changes`` is required here and not defaulted:
    defaulting it would let the two paths judge the same workspace differently,
    which is #1308 re-opened one caller along.

    NEVER RAISES, and that is its whole contract to the terminal paths. It runs
    on an execution that has ALREADY failed or been cancelled for a reason of
    its own, and an exception here would replace that reason with this one - a
    strictly worse error, about a different subject. A workspace that stops
    answering becomes `SavedWork.unreadable`, which reports the absence of a
    verdict rather than a verdict of "nothing was lost".

    "NEVER RAISES" IS ABOUT FAILURES, NOT ABOUT CANCELLATION (#1396). An
    `asyncio.CancelledError` still leaves here, and must: it is not a report
    about this workspace but the caller's own request to stop, and a task that
    swallowed it would go on to report normal completion and could never be
    stopped again. What changed is what happens FIRST - the rescue push is
    made and its outcome written to the log before the cancellation is
    re-applied, where previously the cancellation passed straight through the
    `except Exception` below and the push was never attempted at all.

    THAT MEANS `Exception`, not just the two the gate declares. The two are
    what the gate raises when a command ANSWERED badly; they are not what a
    workspace raises when it cannot run one at all - a container already reaped
    by a restart, a backend whose transport is gone. Those arrive as whatever
    the backend throws, and letting one through would report a docker error as
    the reason a phase timed out. The narrower `except` reads more carefully
    and is wrong here: on this path an unexpected exception is still, exactly,
    "we could not look".

    BOUNDED, because of WHEN it runs. EVERY command it issues carries a bound
    in its own argv - see `workspace_git.run_bounded`, the only place a command reaches
    the workspace and therefore the only place the bound could be left off -
    so the walk costs at worst a fixed wait per command and cannot outlast the
    budget that has already expired.

    "Every" and not "every network one" (#1231). A repository's own
    `.gitattributes` can point `git add --all` and `git status` at a `clean`
    filter that never returns, which made LOCAL commands the way to hang the
    path that exists to stop this phase hanging. A bound that fires arrives
    here as `WorkspaceInspectionFailedError` and leaves as
    `SavedWork.unreadable`, carrying whatever earlier repositories were
    already pushed: cut off is reported as a failure to preserve, never as
    nothing to preserve.
    """
    try:
        await quarantine_unpushed_work(
            workspace,
            execution_id=execution_id,
            phase_id=phase_id,
            delivers_repo_changes=delivers_repo_changes,
        )
    except UnpushedWorkQuarantinedError as saved:
        return SavedWork(quarantined=saved.quarantined)
    except WorkspaceInspectionFailedError as unreadable:
        logger.warning("Could not finish saving this workspace's work: %s", unreadable.summary)
        return SavedWork(quarantined=unreadable.quarantined, unreadable=unreadable.summary)
    except Exception as broken:  # `Exception`, deliberately - see "NEVER RAISES" above
        logger.exception("Could not reach this workspace to save its work")
        return SavedWork(unreadable=f"the workspace could not be reached ({broken})")
    return SavedWork()


def already_saved_by_the_completion_gate(error: BaseException) -> bool:
    """Whether this failure IS the completion gate's refusal, work and all (#1184).

    THE ONE FAILURE THAT ARRIVES WITH THE WORKSPACE ALREADY EMPTIED. Both
    errors below are raised only after `quarantine_unpushed_work` has pushed
    everything it found, and both carry the report of it, which becomes the
    failure's reason. Saving again would find the same work - a quarantine
    pushes to `refs/syn/lost`, which is outside `refs/remotes`, so git still
    calls those commits unpushed afterwards and cannot answer "already saved"
    itself.

    So the message would name one ref twice, under two headlines, about one
    save. That is the certain cost and it is enough on its own: a reader told
    the same commits were saved twice has no way to tell that they were not.

    The uncertain cost is worse and lands on a clock boundary. `workspace_git`'s
    fixed identity pins the author and committer but not the DATE, so the second
    `commit-tree` is the identical object only while both attempts fall in the
    same whole second. Across one, it is a different commit pushed WITHOUT
    force over a ref it does not descend from, rejected as a non-fast-forward,
    and rendered as work that is gone - "NONE OF IT IS RECOVERABLE" directly
    beneath the gate's own "All of it is recoverable", about the same commits,
    one of them false. Asking here is what stops both, and it is asked once.
    """
    return isinstance(error, UnpushedWorkQuarantinedError | WorkspaceInspectionFailedError)


class _UnsavedWork:
    """A repository's unsaved state: what is missing, and from which tips."""

    __slots__ = ("branch", "commit_count", "files", "parents")

    def __init__(
        self,
        *,
        branch: str,
        commit_count: int,
        files: tuple[str, ...],
        parents: tuple[str, ...],
    ) -> None:
        self.branch = branch
        self.commit_count = commit_count
        self.files = files
        #: Commits the quarantine commit must descend from for every unpushed
        #: commit to be reachable through the one ref. HEAD first, so the
        #: recovered history reads as the phase left it.
        self.parents = parents


def _read_only_mount(mount_table: str, path: str) -> bool:
    """Whether the filesystem under ``path`` refuses writes, per mountinfo.

    The DEEPEST mount point containing the path is the one that governs it: a
    writable mount nested inside a read-only one is writable, and stopping at
    the first match would report the opposite. Where two lines mount the same
    point, the later one is the one in force.

    A line this cannot parse is skipped rather than guessed at. The verdict is
    only ever used to WEAKEN the gate, so every uncertainty here resolves to
    "writable", which is the answer that keeps work.
    """
    governing = ""
    deepest = -1
    for line in mount_table.splitlines():
        fields = line.split(" ")
        if len(fields) < _MOUNT_FIELDS:
            continue
        mount_point, options = fields[4], fields[5]
        stem = mount_point.rstrip("/")
        if path != stem and not path.startswith(f"{stem}/"):
            continue
        depth = stem.count("/")
        if depth >= deepest:
            deepest, governing = depth, options
    return _READ_ONLY_OPTION in governing.split(",")


async def _write_protected(workspace: GitWorkspace, repos: list[str]) -> frozenset[str]:
    """Of these repositories, the ones the phase was unable to write to.

    This is the evidence half of the #1308 exemption, and it is evidence
    rather than testimony: a read-only mount is a property of the container
    the phase ran in, fixed before the agent started and beyond its reach
    afterwards. Read once for the whole workspace, because one mount table
    covers every repository in it.

    NOT ``checked``, which is the second and last deliberate exception to
    that rule, alongside ``workspace_git.push``. The rule exists because reading
    an unanswered command as "clean" turns "I could not look" into "I looked
    and it was fine". Here the direction is reversed: a mount table nobody
    could read is no evidence, no evidence exempts nothing, and the phase is
    then judged exactly as strictly as it would have been without this call.
    Failing the gate instead would break every backend that cannot cat a file
    in order to protect nothing.
    """
    result = await run_bounded(workspace, ["cat", _MOUNT_TABLE])
    if not result.success or result.exit_code != 0:
        logger.info(
            "Could not read %s in this workspace (exit %d), so no repository can be "
            "shown to have been write-protected. Every uncommitted change is judged "
            "as work, which is this gate's default.",
            _MOUNT_TABLE,
            result.exit_code,
        )
        return frozenset()
    return frozenset(repo for repo in repos if _read_only_mount(result.stdout, repo))


async def _unsaved_work(
    workspace: GitWorkspace, repo: str, *, uncommitted_is_work: bool
) -> _UnsavedWork | None:
    """What this repository holds that the remote does not, or None if nothing.

    ``uncommitted_is_work`` is the caller's verdict on the dirty tree, not a
    question to be re-litigated here - see `quarantine_unpushed_work` for what
    it takes to make it False. Commits are unaffected by it either way.
    """
    status = await git(workspace, repo, "status", "--porcelain")
    tips = await git(
        workspace, repo, "for-each-ref", "--format=%(objectname) %(refname:short)", "refs/heads"
    )
    # --revs-only, NOT --quiet --verify. Both print the sha and print nothing
    # when the repository has no commits yet, but --verify makes "no commits"
    # an exit 1 - indistinguishable from the workspace being unreachable, which
    # is the exact ambiguity this module refuses to live with. --revs-only
    # answers the empty repository with exit 0 and empty output, so the case
    # stops existing rather than being handled.
    head = await git(workspace, repo, "rev-parse", "--revs-only", "HEAD")

    named: list[tuple[str, str]] = [
        (sha, name) for sha, _, name in (line.partition(" ") for line in tips.splitlines()) if sha
    ]
    head_sha = head.strip()
    # Every tip that could be carrying work, HEAD included so that a detached
    # HEAD is not a case of its own, deduplicated so that a checked-out branch
    # is not listed twice.
    candidates = _dedup([head_sha, *(sha for sha, _ in named)])
    unpushed: set[str] = set()
    if candidates:
        reachable = await git(workspace, repo, "rev-list", *candidates, "--not", "--remotes")
        unpushed = set(reachable.split())

    files = tuple(line.rstrip() for line in status.splitlines() if line.strip())
    # THE ONE LINE THE EXEMPTION DECIDES (#1308). An uncommitted change is
    # evidence of work unless the phase both disclaimed it and was unable to
    # write it, in which case the same line is a build tool that dirtied a
    # tree somebody else's process owns. Commits are untouched by this and
    # are read as work either way - see the module docstring.
    unsaved_files = files if uncommitted_is_work else ()
    if not unpushed and not unsaved_files:
        if files:
            # Said out loud rather than dropped: the tree IS about to be
            # destroyed, and an operator reading this phase's logs after a
            # surprising rebuild deserves to see which paths the phase's own
            # tooling had rewritten.
            logger.info(
                "Leaving %d uncommitted path(s) in %s to the workspace: this phase "
                "declares it delivers no repository changes, and could not have "
                "written them - the repository is mounted read-only. Paths: %s",
                len(files),
                repo,
                ", ".join(files),
            )
        return None

    # `files`, NOT `unsaved_files`. Reaching here means the phase is holding
    # commits, so it authored something and the whole tree goes into the
    # quarantine `git add --all` builds; reporting a subset of what was saved
    # would describe a commit nobody could then read.
    # HEAD is a parent whenever it exists, even when it is fully pushed: it is
    # what makes an uncommitted-changes-only snapshot diffable against the
    # branch it came from.
    return _UnsavedWork(
        branch=_branch_name(head_sha, named),
        commit_count=len(unpushed),
        files=files,
        parents=_dedup([head_sha, *(sha for sha, _ in named if sha in unpushed)]),
    )


async def _quarantine(
    workspace: GitWorkspace,
    repo: str,
    work: _UnsavedWork,
    *,
    ref: str,
) -> tuple[QuarantinedWork, asyncio.CancelledError | None]:
    """Push ``work`` to ``ref`` in ``repo``, say where it landed, and say if cancelled.

    A plain push, never a force: the ref is unique to this phase run, so the
    only thing that could already occupy it is a writer nobody predicted, and
    overwriting that would trade one silent loss for another.

    Only the push may fail and still return. Everything before it - clearing
    the scratch index, staging, writing the tree, writing the commit - is
    checked and raises, because a QuarantinedWork built on top of a command
    that did not run would report work as quarantined that was never written.
    That is the same false reassurance as a false ``completed``, in a smaller
    costume, so the only failure this reports as data is the one that happens
    after the objects exist.

    THE CREDENTIAL IS RENEWED IMMEDIATELY BEFORE THE PUSH, and that is the
    whole of #1393's fix. This runs at teardown, which on a phase that
    exhausted a 3600s budget is by arithmetic later than the one-hour life
    GitHub gives the installation token the setup phase installed - so the
    push that matters most is the one most certain to be refused. Renewing
    here rather than at the top of the walk keeps the cost on the path that
    actually pushes: a clean phase, which is almost all of them, pays nothing
    and needs no flag to remember it.

    A CANCELLATION IS RETURNED, NEVER DROPPED AND NEVER RAISED HERE (#1396).
    `asyncio.CancelledError` is a `BaseException`, so the two "never raises"
    handlers on this path - both written as `except Exception` - let it
    through, and a phase cancelled while its credential was being renewed lost
    the rescue push entirely: the commit exists, the container is about to go,
    and nothing was attempted. So the push is made anyway, under its own
    bound, and the cancellation travels back to the walk as a value - which is
    the only way the record BELOW can be written down before the cancellation
    is re-applied. Swallowing it instead would be worse than the bug: a task
    that reports normal completion after being cancelled is a task nobody can
    stop.
    """
    await checked(
        workspace,
        ["rm", "-f", _SCRATCH_INDEX],
        doing=f"clearing the scratch index before quarantining {repo}",
    )
    await git(workspace, repo, "add", "--all", index=_SCRATCH_INDEX)
    tree = (await git(workspace, repo, "write-tree", index=_SCRATCH_INDEX)).strip()
    parents = [arg for sha in work.parents for arg in ("-p", sha)]
    commit = await git(
        workspace,
        repo,
        "commit-tree",
        tree,
        *parents,
        "-m",
        _commit_message(ref),
        identity=True,
    )
    cancelled = await _renew_credential(workspace, doing=f"quarantining {repo}")
    pushed, cancelled_pushing = await _push_despite_cancellation(
        workspace, repo, commit=commit.strip(), ref=ref
    )
    cancellation = cancelled or cancelled_pushing

    name = repo.rsplit("/", 1)[-1]
    if pushed.exit_code != 0:
        logger.error("Quarantine push failed for %s -> %s: %s", repo, ref, pushed.stderr)
        record = QuarantinedWork(
            repo=name,
            branch=work.branch,
            commit_count=work.commit_count,
            files=work.files,
            pushed_ref=None,
            push_error=(pushed.stderr or pushed.stdout).strip() or "push exited non-zero",
        )
    else:
        logger.warning("Quarantined unpushed work from %s at %s", repo, ref)
        record = QuarantinedWork(
            repo=name,
            branch=work.branch,
            commit_count=work.commit_count,
            files=work.files,
            pushed_ref=ref,
        )
    return record, cancellation


def _quarantine_ref(execution_id: str, phase_id: str) -> str:
    """Where this phase's rescued work goes, and where the rehearsal aims.

    One function because the rehearsal at phase start and the push at teardown
    must name the SAME ref: a rehearsal against a different one would prove
    something true about a ref nobody uses, which is worse than not rehearsing
    at all - it would report a working net that had never been tested.
    """
    return f"{_QUARANTINE_NAMESPACE}/{execution_id}/{phase_id}"


async def _renew_credential(
    workspace: GitWorkspace, *, doing: str
) -> asyncio.CancelledError | None:
    """Give this workspace a usable credential if it can be given one.

    NEVER RAISES, which is the opposite of what the phase-start rehearsal wants
    from the same call and the reason the two ask separately. Here the phase
    has already failed and a commit is waiting to be pushed: a renewal that
    could not happen is a reason the push MIGHT fail, not a reason to skip it.
    The token already in the container may have minutes left, and spending it
    is the only way to find out. So the failure is logged and the push goes
    ahead, where its own result is reported honestly either way.

    NEVER RAISES MEANS ANY EXCEPTION, not just the documented one. The
    protocol says implementations raise `CredentialRenewalFailedError`, and
    catching only that would make this promise conditional on every present
    and future workspace keeping its half of it - while the cost of one that
    does not is precisely #1393's cost: the rescue push is never attempted,
    the commit dies with the container, and the honest `NOT RECOVERABLE`
    report that the push would have produced is never written either. An
    optional improvement to the credential must not be able to take the thing
    it was improving with it, so the second handler is deliberate and not
    defensive clutter: at this point in a phase there is no exception worth
    more than the attempt.

    AND "ANY EXCEPTION" WAS STILL NOT ENOUGH (#1396). `asyncio.CancelledError`
    is a `BaseException` in 3.12, so `except Exception` never saw it: an
    execution cancelled while this await was in flight skipped the push
    completely, which is the one outcome the whole handler exists to prevent,
    arriving by the one route it did not cover. It is RETURNED rather than
    caught-and-forgotten, because a cancelled task that goes on to report
    normal completion cannot be stopped by anyone - the caller pushes, writes
    down what happened, and re-applies it.

    `KeyboardInterrupt` and `SystemExit` are deliberately NOT covered. They
    are the process being told to stop, not this phase; a rescue push that
    outlived a Ctrl-C would be a workspace holding an operator's terminal
    hostage over work they had just said they no longer wanted.

    Returns:
        The cancellation to re-apply once the push has been made and
        reported, or None when nothing cancelled this.
    """
    try:
        await workspace.renew_git_credential()
    except asyncio.CancelledError as cancelled:
        logger.warning(
            "This phase was cancelled while its git credential was being renewed before "
            "%s. The rescue push will still be attempted - with whatever credential the "
            "container already holds - and the cancellation re-applied afterwards.",
            doing,
        )
        return cancelled
    except CredentialRenewalFailedError as unrenewable:
        logger.error(
            "Could not renew this workspace's git credential before %s (%s). The push "
            "will be attempted with the credential already in the container, which on "
            "a phase that ran its full budget has probably expired.",
            doing,
            unrenewable,
        )
    except Exception:
        logger.exception(
            "Renewing this workspace's git credential before %s raised something other "
            "than CredentialRenewalFailedError, which its protocol says it will not. "
            "The push will be attempted with the credential already in the container.",
            doing,
        )
    return None


async def _push_despite_cancellation(
    workspace: GitWorkspace, repo: str, *, commit: str, ref: str
) -> tuple[ExecutionResult, asyncio.CancelledError | None]:
    """The rescue push, given the seconds it needs even while being cancelled.

    THE PUSH IS THE POINT OF THIS WHOLE PATH, and it is one await long. A
    cancellation delivered anywhere in that await - and teardown is exactly
    when cancellations arrive - would otherwise abandon a commit that exists,
    in a container that is about to be destroyed, with the objects nowhere
    else. So the push runs as its own task behind `asyncio.shield`: cancelling
    this coroutine no longer cancels it, and the answer is still collected.

    BOUNDED, because "ignore the cancellation until the push returns" is not a
    promise this may make. `_CANCELLED_PUSH_SECONDS` is the whole of the extra
    time a cancelled phase can cost, after which the push is abandoned and
    reported with `BOUND_FIRED_EXIT_CODE` - the same code the bound inside the
    push's own argv would produce, because a reader needs "the answer never
    came", not which bound produced it. Repeated cancellations are absorbed
    for as long as the deadline allows and no longer, so a caller that cancels
    in a loop cannot be held.

    Returns:
        The push's result, and the first cancellation that arrived while it
        was in flight for the caller to re-apply, or None.
    """
    pushing = asyncio.ensure_future(push(workspace, repo, commit=commit, ref=ref))
    deadline = monotonic() + _CANCELLED_PUSH_SECONDS
    cancelled: asyncio.CancelledError | None = None
    while True:
        try:
            return await asyncio.wait_for(
                asyncio.shield(pushing), timeout=max(0.0, deadline - monotonic())
            ), cancelled
        except asyncio.CancelledError as arrived:
            # The SHIELD is what makes this recoverable: `wait_for` cancelled
            # its own await, never `pushing`, which is still running. Kept to
            # be re-applied, and only the first one - they are the same
            # request, and the caller needs a cancellation, not a count.
            cancelled = cancelled or arrived
            if pushing.done():
                return pushing.result(), cancelled
            if monotonic() >= deadline:
                pushing.cancel()
                return _cut_off(repo, ref), cancelled
        except TimeoutError:
            pushing.cancel()
            return _cut_off(repo, ref), cancelled


def _cut_off(repo: str, ref: str) -> ExecutionResult:
    """What a push that never answered inside its bound is reported as.

    A FAILED PUSH, never an absent one: the objects may or may not have
    reached the remote, so the caller must report the work as unrecoverable
    and name the ref. Reading it as a success is the false reassurance this
    whole module exists to refuse, and reading it as "nothing was attempted"
    would send an operator past a ref that might be there.
    """
    return ExecutionResult(
        exit_code=BOUND_FIRED_EXIT_CODE,
        success=False,
        duration_ms=0.0,
        stderr=(
            f"The rescue push of {repo} to {ref} was still running "
            f"{_CANCELLED_PUSH_SECONDS:.0f}s after this phase was cancelled and was "
            f"abandoned. Whether the ref exists is unknown."
        ),
        timed_out=True,
    )


def _commit_message(ref: str) -> str:
    return (
        f"syn: quarantined work that would have been lost ({ref})\n\n"
        "The phase that produced this ended without pushing it, and its "
        "workspace was about to be destroyed. This commit's tree is the "
        "working tree as it stood; its parents are the local tips carrying "
        "commits the remote did not have.\n"
    )


def _branch_name(head_sha: str, named: list[tuple[str, str]]) -> str:
    """The checked-out branch, or a readable stand-in when HEAD is not on one."""
    if not head_sha:
        return "(no commits)"
    for sha, name in named:
        if sha == head_sha:
            return name
    return "(detached HEAD)"


def _dedup(shas: list[str]) -> tuple[str, ...]:
    """Non-empty SHAs, first occurrence wins, order preserved."""
    return tuple(dict.fromkeys(sha for sha in shas if sha))
