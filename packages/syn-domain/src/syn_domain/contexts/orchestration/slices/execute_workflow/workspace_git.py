"""Asking a live workspace a question, and refusing to read silence as an answer.

ONE PLACE THAT KNOWS HOW TO ASK GIT ANYTHING IN A LIVE WORKSPACE. The two
questions this slice asks of a dying container - "would anything here be lost"
(`unpushed_work_guard`) and "where do these branches stand"
(`branch_observation`) - are different questions with different verdicts, but
they are the same *sequence of commands whose stdout gets parsed*, and they are
wrong in the same way if they read an unanswered command as an answer. So the
asking is one module and the two callers own only their own conclusions. This
is the same invariant the three used to hold as one file, moved to where it can
be stated rather than remembered (#1231).

EVERY COMMAND IS CHECKED, and that is load-bearing rather than tidy. An
unreachable container does not raise - the Docker backend RETURNS a non-zero
result with empty stdout, which is byte-for-byte what a clean workspace
returns. Reading stdout without reading the result therefore turned "I could
not look" into "I looked and it was fine", which is #1184 itself happening
inside the gate against it. `checked` is the single point where a result
becomes readable output, so the discipline holds for commands nobody has
written yet.

EVERY COMMAND IS ALSO BOUNDED, for the same kind of reason one level down.
`run_bounded` is the only place a command reaches the workspace, so the bound
cannot be left off by a caller who forgot it - see `LOCAL_TIMEOUT_SECONDS`
below for why an unbounded command on this path costs an hour.

TWO DELIBERATE EXCEPTIONS to the check, and both are exceptions on purpose:
`push`, whose failure is an answer rather than the lack of one, and
`unpushed_work_guard._write_protected`, which reads the mount table through
`run_bounded` directly because there the unreadable case must weaken the gate
rather than fail it. Both say so at their own definition. Nothing else may.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    FailedWorkspaceCommand,
    WorkspaceInspectionFailedError,
)
from syn_shared.workspace_paths import WORKSPACE_REPOS_DIR

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

#: commit-tree needs an identity and the container may have none: the setup
#: script configures user.name only when GIT_AUTHOR_NAME was supplied. Stating
#: it here removes that dependency; it matches the setup script's own fallback.
_IDENTITY: Final[tuple[str, ...]] = (
    "GIT_AUTHOR_NAME=syn-bot",
    "GIT_AUTHOR_EMAIL=agent@agentic.local",
    "GIT_COMMITTER_NAME=syn-bot",
    "GIT_COMMITTER_EMAIL=agent@agentic.local",
)

#: How long a command is given before it is cut off. EVERY command this slice
#: runs carries one of these, because these paths run while a phase is already
#: failing and teardown is queued behind them: whatever it costs must be a
#: bounded wait rather than the container's remaining lifetime. Without a
#: bound the wait is not "however long the container has left" either - it is
#: the backend's default execute timeout, which is an HOUR (#1231).
#:
#: TWO NUMBERS BECAUSE THEY ANSWER TWO QUESTIONS, and the local one being the
#: larger is not a mistake: a remote that has not said hello in twenty seconds
#: is not going to, while `add --all` re-hashing a cold, large worktree is
#: this container doing real work and may legitimately take longer than that.
#:
#: THE LOCAL BOUND WAS THE HOLE. The remote pair were bounded first, on the
#: reasoning that a local git command which hangs is a broken container and
#: nothing here can help it. That was wrong, and repository-controlled code is
#: why: `.gitattributes` names a `clean` filter, the repository's own config
#: supplies the program, and both `git status` and `git add --all` run it over
#: the worktree. A filter that sleeps then holds the preservation path open
#: for the full hour - the unbounded failure that preserving the work exists
#: to prevent, reached through the preserving. A repository big enough to
#: exceed the bound honestly is reported as work that could not be preserved,
#: which is the true answer and one an operator can act on.
#:
#: `--kill-after` covers a child that ignores the first signal - a transport
#: helper, or a filter sitting in an uninterruptible read.
#:
#: Carried in argv through coreutils `timeout`, for the reason `git_argv`
#: already carries environment through `env`: the command stays self-contained
#: and asks nothing of the execute() port, which every backend and every
#: double would then have to implement. The two programs ship together, so a
#: workspace with `env` has this. One that somehow has neither exits 127 -
#: a command that did not answer, which `checked` already refuses to read as
#: one.
#:
#: Public, and read through the module global rather than baked into a
#: default, so that a test can lower either bound and have `run_bounded` obey
#: it - which is how the hanging-filter regression is made to run in seconds.
REMOTE_TIMEOUT_SECONDS: Final[int] = 20
LOCAL_TIMEOUT_SECONDS: Final[int] = 30
KILL_AFTER_SECONDS: Final[int] = 5

#: Hooks off, in front of every git command this slice runs (#1231). A hook
#: is a program the REPOSITORY supplies and git executes - `pre-push` on the
#: quarantine push is the live one here, and it hangs that push exactly as a
#: `clean` filter hangs `add`. That path empties a workspace the repository's
#: owner never asked it to empty, at a moment when the budget is already
#: spent, so there is no hook whose opinion is wanted and none is consulted.
#:
#: Worth having ON TOP OF the bound because it is the one COMPLETE
#: neutralisation available: git looks for hooks in exactly one directory, so
#: pointing that at a non-directory closes the entire class at once, leaves
#: nothing partially covered, and needs no maintenance. It is also the only
#: level that can close it: the image entrypoint already points
#: `core.hooksPath` at its own directory, which incidentally hides a
#: repository's `.git/hooks` - but a repository's own `.git/config` outranks
#: that, and only `-c` on the command line outranks the repository.
#:
#: The same reasoning, and the same `/dev/null`, as the provisioning clone in
#: `setup_phase_secrets`. Nothing of OURS is lost by it: the image's hook is
#: `prepare-commit-msg`, and the quarantine commit is written by
#: `commit-tree`, which is plumbing and consults no hook in any case.
#:
#: FILTERS ARE NOT CLOSED THE SAME WAY, deliberately, and the asymmetry is the
#: decision rather than an omission. A `clean` filter is named by the
#: repository's `.gitattributes` and its program comes from the repository's
#: config, so switching them off means reading that config, listing the driver
#: names and overriding each: more repository-derived input, and more
#: commands, on the path with the least budget left. The single switch that
#: would do it, `--attr-source`, arrived in git 2.40 and the workspace image
#: ships 2.39 - there, passing it fails every command and destroys the path it
#: was meant to protect.
#:
#: It would also change WHAT gets preserved. git-lfs is a `clean` filter:
#: neutralised, `add --all` stages the real bytes instead of the pointers and
#: the quarantine push must then carry a whole worktree over the network
#: inside `REMOTE_TIMEOUT_SECONDS`. That trades "the work was saved" for "the
#: push was too big" in every LFS repository, to close a case the bound has
#: already closed.
#:
#: And hooks and filters are not the whole class in any event: `core.fsmonitor`,
#: `credential.helper`, an `ext::` remote URL and textconv drivers are all
#: programs a repository's config can hand to git. A list of `-c` overrides
#: would close the ones known today and fall behind git's next release. The
#: BOUND closes all of them, including the ones not yet invented, because it
#: does not care what the program is - only how long it may take. The bound is
#: the guarantee; hooks off is the extra that costs nothing.
_HOOKS_OFF: Final[tuple[str, ...]] = ("-c", "core.hooksPath=/dev/null")

#: `timeout`'s documented exit code for "the bound fired". Named here because
#: this module is what put the wrapper in the argv, so this module is what can
#: say that 124 means the command was cut off rather than that it answered
#: 124. Without it an operator reads "exited 124" and has to go and look it up.
#:
#: Public so that a caller which cut a command off ITSELF can report the same
#: code rather than inventing a second one (#1396): the salvage push in the
#: unpushed-work guard bounds its own wait when the phase is being cancelled,
#: and a reader must not have to know which of the two bounds fired to know
#: that the answer never arrived.
BOUND_FIRED_EXIT_CODE: Final[int] = 124


class GitWorkspace(Protocol):
    """A workspace this slice can run git in, and whose credential it can renew.

    TWO CAPABILITIES AND NOT ONE, because every git command here that reaches
    a remote spends a credential with a shorter life than the container's.
    The workspace's is a GitHub App installation token: minted once during
    provisioning, capped by GitHub at an hour, and never extended. A phase may
    run for longer than that, and the commands that matter most here - the
    quarantine push, the rehearsal that proves it would work - run at the two
    ends of that window. So "can I run a command in it" is not enough to know
    a push will be authorised, and a protocol that promised only the first
    would have every caller discovering the second by being refused (#1393).

    `renew_git_credential` is therefore not an optional extra a caller probes
    for. A double that cannot renew is not a workspace this slice can be
    trusted against, and making it part of the protocol is what says so at the
    type level rather than at teardown.
    """

    async def execute(self, command: list[str]) -> ExecutionResult: ...

    async def renew_git_credential(self) -> None:
        """Install a freshly minted credential, or raise `CredentialRenewalFailedError`.

        Says nothing about whether the credential it replaced still worked -
        see that error for why nothing can.
        """
        ...


async def run_bounded(
    workspace: GitWorkspace, command: list[str], *, timeout_seconds: int | None = None
) -> ExecutionResult:
    """Run ``command`` in ``workspace`` under a time bound, and return its result.

    THE ONLY PLACE this slice hands a command to a workspace, which is what
    makes the bound impossible to forget rather than merely present wherever
    someone remembered it (#1231). It is `checked`'s argument one level down:
    that one exists so a caller cannot read an unanswered command as an
    answer; this one exists so a caller cannot wait on one forever. Add a
    command, get the check - and now get the bound too.

    ``timeout_seconds`` defaults to the local bound because all but two of
    these commands are local. The two that ask a remote pass the remote one
    and say why at the call.

    Read through the module global rather than as a parameter default so that
    a test can lower either bound and have this obey it.
    """
    bound = LOCAL_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    return await workspace.execute(
        ["timeout", f"--kill-after={KILL_AFTER_SECONDS}", str(bound), *command]
    )


async def checked(
    workspace: GitWorkspace, command: list[str], *, doing: str, timeout_seconds: int | None = None
) -> str:
    """Run ``command`` and return its stdout, or raise if it did not succeed.

    THE ONE PLACE a command result becomes something this slice reads, and
    therefore the one place that decides a result can be trusted. The check
    lives here rather than in each caller on purpose: the callers are nothing
    but sequences of commands whose stdout they parse, and one that forgot to
    check would silently read "" as "clean" - which is exactly the defect the
    guard exists to stop, turned inward. Add a command, get the check.

    Success is all three of exit 0, ``success``, and not timing out. A backend
    that sets only one of the first two should not slip through on the other,
    and a command that was killed part-way printed a prefix of an answer, not
    an answer.

    Returns:
        stdout. Never the ExecutionResult - handing that back would put the
        unchecked value in reach again.

    Raises:
        WorkspaceInspectionFailedError: the command failed, so it produced no
            verdict and this module refuses to invent one.
    """
    result = await run_bounded(workspace, command, timeout_seconds=timeout_seconds)
    if result.success and result.exit_code == 0 and not result.timed_out:
        return result.stdout
    raise WorkspaceInspectionFailedError(
        doing=doing,
        failure=FailedWorkspaceCommand(
            # The command as the caller MEANT it, without the bound
            # `run_bounded` wrapped around it. The wrapper is this module's own
            # machinery and naming it in the failure would put `timeout
            # --kill-after=5 30` in front of the git command an operator is
            # trying to read; `timed_out` below already carries everything it
            # would tell them.
            command=tuple(command),
            exit_code=result.exit_code,
            stderr=result.stderr,
            # Two ways to be cut off and one word for it: the BACKEND says so
            # when it enforced its own limit, and `timeout` says so with an
            # exit code when the bound `run_bounded` put in the argv fired. A
            # reader needs "it did not finish" either way, not a number. Every
            # command goes through `run_bounded`, so 124 can be read this way
            # whatever the command was.
            timed_out=result.timed_out or result.exit_code == BOUND_FIRED_EXIT_CODE,
        ),
    )


async def repositories(workspace: GitWorkspace) -> list[str]:
    """Absolute paths of the repositories cloned into this workspace.

    Empty means the execution was configured with no repositories - a real and
    common case, so it stays a success. It can only mean that because the
    search itself is checked: ``/workspace/repos`` is created by the image and
    again by the entrypoint, so on any workspace that answers at all this find
    exits 0 whether or not it matched anything, and a non-zero one is the
    workspace declining to answer rather than an answer of "nothing here".

    SCOPE, stated because it is a real limit. Repositories are the ones cloned
    directly under ``/workspace/repos``. Work committed inside a SUBMODULE of
    one of those is DETECTED - the superproject reports a modified gitlink, so
    the phase still fails rather than silently succeeding - but the submodule's
    own objects are not quarantined, because they belong to a different remote.
    A submodule's commits are recoverable only if the phase pushed them itself.
    """
    found = await checked(
        workspace,
        ["find", str(WORKSPACE_REPOS_DIR), "-mindepth", "2", "-maxdepth", "2", "-name", ".git"],
        doing=f"listing the repositories under {WORKSPACE_REPOS_DIR}",
    )
    suffix = "/.git"
    return sorted(line.strip()[: -len(suffix)] for line in found.splitlines() if line.strip())


def git_argv(repo: str, *args: str, index: str | None = None, identity: bool = False) -> list[str]:
    """Argv for one git command in ``repo``, with no hook of the repository's own.

    Environment is carried in argv, via ``env``, rather than through the
    execute() port's channels: the command is then self-contained and behaves
    identically on any backend that can merely run a process, including the
    doubles that only run one. The time bound is `run_bounded`'s, for the same
    reason one level up - it belongs to every command and not only to git's.

    `_HOOKS_OFF` goes on every command rather than only on `push`, the one
    that runs a hook today: which subcommands consult hooks is git's business
    and changes between releases, and a prefix applied to all of them cannot
    be left off the one that starts to.
    """
    prefix: list[str] = []
    if index is not None:
        prefix.append(f"GIT_INDEX_FILE={index}")
    if identity:
        prefix.extend(_IDENTITY)
    env = ["env", *prefix] if prefix else []
    return [*env, "git", *_HOOKS_OFF, "-C", repo, *args]


async def git(
    workspace: GitWorkspace,
    repo: str,
    *args: str,
    index: str | None = None,
    identity: bool = False,
) -> str:
    """Stdout of one git command in ``repo``, or raise if it failed."""
    return await checked(
        workspace,
        git_argv(repo, *args, index=index, identity=identity),
        doing=f"running 'git {args[0]}' in {repo}",
    )


async def git_remote(workspace: GitWorkspace, repo: str, *args: str, doing: str) -> str:
    """Stdout of one git command that TALKS TO A REMOTE, under the remote bound.

    Exists so that `REMOTE_TIMEOUT_SECONDS` is named in exactly one module.
    A caller that passed the bound itself would hold a second copy of it -
    imported by value, so a test that lowers the bound here would not lower
    that one, and the hang it was written to catch would go uncaught while the
    test still read as if it covered it.

    ``doing`` is the caller's, not derived from argv like `git`'s: a remote
    command's failure is about the remote, and "asking origin where fix/x is"
    is what an operator needs to read, not "running 'git ls-remote'".
    """
    return await checked(
        workspace, git_argv(repo, *args), doing=doing, timeout_seconds=REMOTE_TIMEOUT_SECONDS
    )


async def push(
    workspace: GitWorkspace, repo: str, *, commit: str, ref: str, dry_run: bool = False
) -> ExecutionResult:
    """The one command whose failure is an answer rather than the lack of one.

    A push can fail for reasons that say nothing about whether the workspace
    is reachable - no credential, no network, the remote rejecting the ref -
    and by the time it runs the quarantine commit already exists locally. So
    its result is returned rather than raised on, and the caller reports the
    work as NOT recoverable. Every other git command here goes through
    `checked`.

    BOUNDED LIKE `ls-remote`, and for a sharper version of the same reason
    (#1231). This is the second network call in the slice and it had no bound
    at all: a remote that accepts a connection and then stops talking held the
    workspace open for the backend's default execute timeout, which is an HOUR.
    On the completion path that merely delayed a phase that had time. On the
    timeout path, where `save_unpushed_work` calls it, the budget is already
    spent and teardown is queued behind it, so an unbounded push turns the
    bounded failure #1231 is about into an unbounded one - the exact outcome
    preserving the work was meant to avoid.

    A push cut off by the bound exits 124 and is reported as a failed push,
    which is the honest reading: the objects exist locally, the ref may or may
    not have landed, and the caller must not promise it did.

    ``dry_run`` is the SAME push with the last steps left out, and the
    sameness is the point rather than a convenience (#1393). git still
    contacts the remote, still authenticates, and still negotiates with
    ``git-receive-pack``; what it does not do is send objects or ask for any
    ref to move. That is what makes the rehearsal the guard runs at phase
    start evidence about THIS command - one function, one argv, one
    credential, so the two cannot drift into testing different things. It is a
    flag rather than a second function for exactly that reason.

    WHAT A DRY RUN CANNOT SEE (#1396): the update itself. ``receive-pack``
    runs ``pre-receive``, evaluates rulesets and locks refs only for a real
    update, so a remote that accepts the connection and then declines
    ``refs/syn/lost`` returns 0 here and non-zero for the real push. Callers
    must not read a dry run as "this push would be accepted"; the guard's
    `rehearse_quarantine_credential` is named and documented for the narrower
    claim that is actually true.
    """
    return await run_bounded(
        workspace,
        git_argv(repo, "push", *(("--dry-run",) if dry_run else ()), "origin", f"{commit}:{ref}"),
        timeout_seconds=REMOTE_TIMEOUT_SECONDS,
    )
