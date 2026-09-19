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
    QuarantinedWork,
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
    ref = f"{_QUARANTINE_NAMESPACE}/{execution_id}/{phase_id}"
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
