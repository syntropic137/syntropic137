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

THREE DELIBERATE EXCEPTIONS to the check, and all three are exceptions on
purpose: `push`, whose failure is an answer rather than the lack of one;
`unpushed_work_guard._write_protected`, which reads the mount table through
`run_bounded` directly because there the unreadable case must weaken the gate
rather than fail it; and `_http_statuses`, for the same reason one layer over -
a transport log that cannot be read leaves the verdict LESS definitive, and
less definitive can only let a phase run. Each says so at its own definition.
Nothing else may.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final, Protocol
from uuid import uuid4

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

#: git's documented exit status for "the connection worked, the remote
#: answered, and it declined to move a ref": some refs could not be pushed.
#: Distinct from 128, which is a fatal error before any ref was discussed.
#: This is an EXIT STATUS rather than a message, so it survives translation
#: and rewording, which is the whole reason the classification prefers it.
_REF_LEVEL_REJECTION_EXIT: Final[int] = 1

#: Where a push's transport log is written INSIDE the workspace, and then read
#: back for status codes and deleted. A file rather than stderr, deliberately:
#: git's curl trace carries the request headers, and on a remote whose URL
#: embeds a token it carries that too. Confined to a file in the container the
#: credential already lives in, only the matched status codes ever come out,
#: and nothing of the trace can reach a log line or an operator's error
#: message. `uuid4` because two repositories are walked in the same container.
_TRANSPORT_LOG_DIR: Final[str] = "/tmp"

#: HTTP's own status line, as git's curl trace records it arriving. This is
#: the ONE machine-readable thing that separates "origin refused you" from
#: "the network broke": measured on the workspace image's git 2.39.5, a DNS
#: failure, a refused connection and an HTTP 401, 403, 500 or 502 ALL exit 128
#: and all report the same ``"code":128`` through `GIT_TRACE2_EVENT`, and
#: 403 and 502 even share one error ``fmt``. Only the status differs.
#:
#: NOT A MATCH ON AN ERROR MESSAGE, which is the distinction that matters. A
#: status code is defined by RFC 9110 and emitted by the SERVER; git's error
#: prose is written by git, passed through ``_()`` and therefore translated,
#: so a classifier built on it changes meaning with the operator's locale and
#: silently with git's next release. This matches neither git's wording nor
#: its translations - it reads the number the remote itself sent.
_HTTP_STATUS_LINE: Final[str] = "Recv header: HTTP/[0-9.]+ [0-9][0-9][0-9]"
_HTTP_STATUS: Final[re.Pattern[str]] = re.compile(r"HTTP/[0-9.]+ ([0-9]{3})$")

#: 4xx is the client's fault by definition - the request will not start
#: working if it is repeated. For a push that means authorization or policy:
#: 401 a credential the remote would not take, 403 one it took and will not
#: let write, 404 a repository this credential cannot see. 5xx is the
#: server's, and a server's fault is a reason to try later, not a verdict
#: about this workspace's credential.
_REFUSING_STATUS: Final[range] = range(400, 500)

#: Turns the curl trace on for one command, with the body dumps off (they are
#: pack data and enormous) and redaction explicitly on rather than relied on
#: as a default.
_TRANSPORT_LOG_ENV: Final[tuple[str, ...]] = ("GIT_TRACE_CURL_NO_DATA=1", "GIT_TRACE_REDACT=1")


class PushVerdict(Enum):
    """What a push outcome is evidence OF - which is not the same as whether it worked.

    THE DISTINCTION #1396 WAS REOPENED FOR. The rehearsal at phase start
    promises exactly two things, a credential and a connection, and it may
    refuse a phase only on the first. Counting attempts cannot tell those
    apart: the third failure of a persistent 502, a DNS outage or a reset
    connection arrives identically to the third failure of an expired token,
    and reading the count as a verdict ended viable phases before their agent
    ran. So every non-zero push is CLASSIFIED, and only one of these four may
    refuse anything.

    `REFUSED` is the narrow one and is the only definitive member: the remote
    answered, and what it answered was about authorization or policy - a 4xx
    on the ref advertisement, or a ref-level rejection from ``receive-pack``.

    `TRANSPORT_FAULT` is everything else that came back. It is deliberately
    the DEFAULT for an outcome this module cannot place, because "not
    definitive" is the honest reading of an unclassifiable failure and the
    rule is that only a definitive refusal may refuse.

    `NO_ANSWER` is `answered`'s case: nothing came back within the bound, so
    there is not even a failure to classify. Separate from `TRANSPORT_FAULT`
    only because an operator reading a warning needs to know which happened;
    both of them let a phase start.
    """

    ACCEPTED = "accepted"
    REFUSED = "refused"
    TRANSPORT_FAULT = "transport fault"
    NO_ANSWER = "no answer"


@dataclass(frozen=True, slots=True)
class ObservedPush:
    """A push, and what its outcome is evidence of.

    Both halves together because a caller needs both and reading them from
    two places is how they drift: the verdict decides what happens, and the
    result carries what to tell an operator it was.
    """

    result: ExecutionResult
    verdict: PushVerdict


def answered(result: ExecutionResult) -> bool:
    """Whether a command produced a result at all, or was cut off before one arrived.

    THE ONE PLACE that decides what "it did not finish" looks like, so that a
    caller asking it gets the whole rule rather than the half it remembered.
    Two ways to be cut off and one word for it: the BACKEND says so when it
    enforced its own limit, and `timeout` says so with `BOUND_FIRED_EXIT_CODE`
    when the bound `run_bounded` put in the argv fired. Every command on this
    path goes through `run_bounded`, so both readings are available for any of
    them.

    FALSE IS NOT "IT FAILED" - it is the stronger and narrower statement that
    NO ANSWER EXISTS. A command that ran and exited non-zero answered: the
    remote said no, the path was not a repository, git refused the argv. That
    distinction is what `unpushed_work_guard` spends when it decides whether a
    failed rehearsal is a verdict about the phase or merely silence (#1396),
    and it is why this is a predicate about the result rather than a flag the
    caller sets from what it was expecting.

    WHAT IT DOES NOT SEPARATE, stated here because the limit is load-bearing
    and invisible otherwise: among commands that DID answer, git does not
    distinguish an authorization refusal from a transport fault. Measured on
    the workspace image's git 2.39.5 - a DNS failure, a refused connection, an
    HTTP 401, 403, 500 and 502 all exit 128, and `GIT_TRACE2_EVENT` reports
    the same ``"code":128`` and the same error ``fmt`` for every one of them.
    The only datum that differs is the prose in the message. So a caller can
    learn from this whether an answer arrived, and must not believe it can
    learn from anything here WHY the answer was no.
    """
    return not (result.timed_out or result.exit_code == BOUND_FIRED_EXIT_CODE)


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
            # A reader needs "it did not finish", not a number, and there is
            # more than one way for a command not to finish. `answered` is
            # where that rule is stated; holding a second copy of it here is
            # how the two drift.
            timed_out=not answered(result),
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


def git_argv(
    repo: str,
    *args: str,
    index: str | None = None,
    identity: bool = False,
    transport_log: str | None = None,
) -> list[str]:
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

    ``transport_log`` asks git to record what the transport actually did, to
    a file in the workspace. Purely an observation - it changes nothing about
    what git sends, receives or decides - and off by default, because the one
    caller that wants it is the one that has to classify a failure
    (`observed_push`).
    """
    prefix: list[str] = []
    if index is not None:
        prefix.append(f"GIT_INDEX_FILE={index}")
    if identity:
        prefix.extend(_IDENTITY)
    if transport_log is not None:
        prefix.extend((f"GIT_TRACE_CURL={transport_log}", *_TRANSPORT_LOG_ENV))
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
    workspace: GitWorkspace,
    repo: str,
    *,
    commit: str,
    ref: str,
    dry_run: bool = False,
    transport_log: str | None = None,
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
        git_argv(
            repo,
            "push",
            *(("--dry-run",) if dry_run else ()),
            "origin",
            f"{commit}:{ref}",
            transport_log=transport_log,
        ),
        timeout_seconds=REMOTE_TIMEOUT_SECONDS,
    )


async def observed_push(
    workspace: GitWorkspace, repo: str, *, commit: str, ref: str, dry_run: bool = False
) -> ObservedPush:
    """`push`, plus what its outcome is evidence of.

    THE MISSING HALF OF THE PORT (#1396). A caller that has to decide whether
    a failed push is a verdict about this workspace's credential cannot get
    that from `ExecutionResult`: the type carries an exit code, and the exit
    code is 128 for an expired token, a DNS outage, a refused connection and
    a 502 alike. Deciding it in the caller therefore meant deciding it from a
    field that does not hold the answer, and every future caller needing the
    same distinction would have rediscovered the same gap. It is answered
    here, at the boundary that can actually see the transport, once.

    HOW, in one sentence: the same push, asked to write down what the
    transport did, read back for status codes only, and the log deleted. The
    round trip costs two local commands on top of a command that just went to
    the network, and it buys the only signal git 2.39.5 has that separates a
    refusal from a fault - see `_HTTP_STATUS_LINE` for why the status and not
    the message.

    THE LOG IS DELETED WHETHER OR NOT IT COULD BE READ, and reading it is
    never allowed to fail the call: a workspace that cannot produce a
    transport log yields no statuses, which lands on `TRANSPORT_FAULT`, which
    lets the phase run. The failure direction is deliberate - a classifier
    that could not classify must not be spent as a refusal.
    """
    log = f"{_TRANSPORT_LOG_DIR}/syn-push-transport-{uuid4().hex}.log"
    result = await push(workspace, repo, commit=commit, ref=ref, dry_run=dry_run, transport_log=log)
    statuses = await _http_statuses(workspace, log)
    return ObservedPush(result=result, verdict=_verdict(result, statuses))


async def _http_statuses(workspace: GitWorkspace, log: str) -> tuple[int, ...]:
    """Every HTTP status the remote sent during one push, in order, and nothing else.

    UNCHECKED ON PURPOSE - the module docstring's third exception. `grep`
    exits non-zero when it matched nothing, which is the ordinary outcome for
    a remote that is not HTTP at all, and a workspace too broken to hold a
    file is one this call must survive rather than one it may fail. Every one
    of those paths returns an empty tuple, and an empty tuple is the input
    that makes `_verdict` LESS willing to refuse.

    ``-o`` is what keeps this safe rather than tidy: only the matched status
    lines cross back out of the workspace, so the request headers the trace
    also holds cannot reach a caller, a log or an operator's error message.
    """
    found = await run_bounded(workspace, ["grep", "-oE", _HTTP_STATUS_LINE, log])
    await run_bounded(workspace, ["rm", "-f", log])
    return tuple(
        int(matched.group(1))
        for line in found.stdout.splitlines()
        if (matched := _HTTP_STATUS.search(line.strip()))
    )


def _verdict(result: ExecutionResult, statuses: tuple[int, ...]) -> PushVerdict:
    """Place one push outcome, preferring the signal the remote itself produced.

    THE ORDER IS THE RULE. A 4xx is the remote answering about authorization
    or policy and is the only thing here that may refuse a phase. A ref-level
    rejection is the same kind of answer arriving through `receive-pack`
    instead of through HTTP, and is read from an exit STATUS rather than from
    the reason git printed beside it. Everything else that came back is a
    fault, including everything this module cannot place: refusing on an
    outcome nobody has classified is exactly the defect #1396 reopened for.
    """
    if result.success and result.exit_code == 0 and not result.timed_out:
        return PushVerdict.ACCEPTED
    if not answered(result):
        return PushVerdict.NO_ANSWER
    if any(status in _REFUSING_STATUS for status in statuses):
        return PushVerdict.REFUSED
    if result.exit_code == _REF_LEVEL_REJECTION_EXIT:
        return PushVerdict.REFUSED
    return PushVerdict.TRANSPORT_FAULT
