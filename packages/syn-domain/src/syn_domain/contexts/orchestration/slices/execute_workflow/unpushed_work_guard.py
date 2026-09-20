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

import logging
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    CredentialRenewalFailedError,
    QuarantinedWork,
    QuarantinePathUnusableError,
    SavedWork,
    UnpushedWorkQuarantinedError,
    WorkspaceInspectionFailedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
    GitWorkspace,
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

    Raises:
        QuarantinePathUnusableError: origin could not be reached with a
            credential, or the credential it depends on could not be renewed.
        WorkspaceInspectionFailedError: the workspace would not answer, so
            nothing was rehearsed and no verdict exists. Propagated rather
            than downgraded, for the reason every command in this module is
            checked: "I could not look" must never be spent as "I looked and
            it was fine".
    """
    repos = await repositories(workspace)
    if not repos:
        return
    try:
        await workspace.renew_git_credential()
    except Exception as unrenewable:
        # ANY exception, for the same reason the teardown caller swallows any:
        # the protocol names one type, and a policy that only applied to that
        # one would be a policy conditional on every workspace keeping its
        # half of it. Here the conclusion is identical whatever was raised -
        # this workspace cannot be given a credential, so an hour from now it
        # will not be able to hand back the work it was given. What differs is
        # only that the phase now fails by NAME rather than by whatever the
        # isolation provider happened to call the problem.
        raise QuarantinePathUnusableError(
            phase_id=phase_id,
            detail=(
                f"The credential every quarantine push depends on could not be "
                f"renewed: {unrenewable}"
            ),
        ) from unrenewable

    ref = _quarantine_ref(execution_id, phase_id)
    for repo in repos:
        head = (await git(workspace, repo, "rev-parse", "--revs-only", "HEAD")).strip()
        if not head:
            continue
        rehearsed = await push(workspace, repo, commit=head, ref=ref, dry_run=True)
        if rehearsed.exit_code != 0:
            raise QuarantinePathUnusableError(
                phase_id=phase_id,
                detail=(
                    f"A rehearsal push of {repo} to {ref} could not reach origin "
                    f"with a credential: "
                    f"{(rehearsed.stderr or rehearsed.stdout).strip() or 'no output'}"
                ),
            )
    logger.info(
        "Phase %s holds a credential that reaches origin, so a quarantine push to %s "
        "would be attempted with one. Server-side acceptance of that ref is NOT "
        "covered by this rehearsal (#1396).",
        phase_id,
        ref,
    )


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
                quarantined.append(await _quarantine(workspace, repo, work, ref=ref))
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
) -> QuarantinedWork:
    """Push ``work`` to ``ref`` in ``repo`` and report where it landed.

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
    await _renew_credential(workspace, doing=f"quarantining {repo}")
    pushed = await push(workspace, repo, commit=commit.strip(), ref=ref)

    name = repo.rsplit("/", 1)[-1]
    if pushed.exit_code != 0:
        logger.error("Quarantine push failed for %s -> %s: %s", repo, ref, pushed.stderr)
        return QuarantinedWork(
            repo=name,
            branch=work.branch,
            commit_count=work.commit_count,
            files=work.files,
            pushed_ref=None,
            push_error=(pushed.stderr or pushed.stdout).strip() or "push exited non-zero",
        )
    logger.warning("Quarantined unpushed work from %s at %s", repo, ref)
    return QuarantinedWork(
        repo=name,
        branch=work.branch,
        commit_count=work.commit_count,
        files=work.files,
        pushed_ref=ref,
    )


def _quarantine_ref(execution_id: str, phase_id: str) -> str:
    """Where this phase's rescued work goes, and where the rehearsal aims.

    One function because the rehearsal at phase start and the push at teardown
    must name the SAME ref: a rehearsal against a different one would prove
    something true about a ref nobody uses, which is worse than not rehearsing
    at all - it would report a working net that had never been tested.
    """
    return f"{_QUARANTINE_NAMESPACE}/{execution_id}/{phase_id}"


async def _renew_credential(workspace: GitWorkspace, *, doing: str) -> None:
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
    """
    try:
        await workspace.renew_git_credential()
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
