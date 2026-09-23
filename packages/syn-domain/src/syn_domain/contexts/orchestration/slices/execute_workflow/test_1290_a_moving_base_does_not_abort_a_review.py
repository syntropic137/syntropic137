"""A review is pinned to its head, and `origin/main` moving does not abort it (#1290).

exec-9819ef91729e reviewed PR #1244 at head `ba307b7a`. PR #1287 merged while it
ran, `origin/main` went from `492ac8f6` to `c8a67374`, and the `verify` phase
halted at its ref-integrity gate. The head had not moved - `verify` re-fetched
and confirmed it. $10.09 bought no verdict.

The gate was right to exist and wrong in what it compared. It ran
``git rev-parse origin/main origin/<pr-branch>`` as ONE assertion against the
recorded SHAs, so either ref moving halted the run - and on a repository where a
queue merges to main, the base moving is the normal condition. That made reviews
and merges mutually exclusive, which is to say the failure rate rose with exactly
the concurrency the platform exists to provide.

WHY THESE TESTS RUN THE PROMPT'S COMMANDS INSTEAD OF MATCHING ITS TEXT. The
first attempt at this fix asserted that a gate line matched ``must equal the
recorded`` and did not contain ``origin/main``. Pointing that line at
``origin/some-unrelated-branch`` left all six cases green: the assertion was
about the shape of a sentence, and the bug is about which commit gets read. A
prompt only has text, but the part of it that decides behaviour is a shell
script, so these tests execute it.

Each test builds a throwaway origin (``main``, a PR branch and an unrelated
branch, all at different commits), clones it onto the default branch exactly as
a phase workspace arrives, runs the ``investigate`` block to produce the two
SHAs, moves ``origin/main`` underneath it, and then runs the ``verify`` block
with the recorded SHAs substituted in. The assertion is on
``git rev-parse HEAD`` of that clone - the commit the worktree actually resolves
to - and never on the ref name the prompt asked for. Aim the gate anywhere but
the PR and the SHA stops matching.

That also wires the producer to the consumer: the values fed into ``verify``
are whatever ``investigate`` printed, and any placeholder ``verify`` names that
``investigate`` does not produce is an unsubstituted ``<...>`` the run fails on.
``pr-review-slp`` had no ref-resolution step at all while carrying a
byte-identical copy of the gate, which is exactly that failure.

The over-correction is covered too: a prompt that simply stopped gating would
let a review certify a head nobody read, so one case moves the HEAD instead of
the base and requires the script to exit non-zero.

WHY IT GOES THROUGH EXECUTION AND NOT `Path.read_text`. The prompt travels
`prompt_file` -> `prompt_template` -> `CreateWorkflowTemplateCommand` ->
`WorkflowTemplateCreated` -> JSON in the event store -> `WorkflowTemplateAggregate`
-> `ExecutablePhase`. Reading the .md file would prove the file, and the file is
not what the agent is handed.

WHY BOTH WORKFLOWS. `pr-review-slp` keeps byte-identical copies of `verify.md`
and `report.md` and says so in its own YAML. Nothing mechanically forces them to
agree, so a fix applied to one arm is the drift this repository has been bitten
by before. Parametrising is what makes a half-fix red.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_WORKFLOWS = Path(__file__).resolve().parents[8] / "workflows"

#: Every workflow in this repository that reviews a pull request.
_REVIEW_WORKFLOWS = ["sdlc/pr-review", "sdlc/pr-review-slp"]

#: The one fenced ``bash`` block in a review prompt: the commands that resolve
#: and pin the refs. A phase prompt is prose plus this script, and the script is
#: the only part of it with a testable exit status, so it is tagged to be found
#: and the tests below refuse a prompt that carries more than one.
_BASH_BLOCK = re.compile(r"^```bash\n(.*?)^```", re.MULTILINE | re.DOTALL)

#: Fenced blocks the report phase gives as the literal shape of a verdict line.
_TEXT_BLOCK = re.compile(r"^```text\n(.*?)^```", re.MULTILINE | re.DOTALL)

#: A whole line that is a resolved commit. ``git diff`` prints abbreviated
#: hashes inside ``index`` lines, never a bare 40-character one, so this picks
#: out exactly what ``git rev-parse`` emitted and in the order it emitted it.
_RESOLVED_SHA = re.compile(r"^[0-9a-f]{40}$", re.MULTILINE)

#: The placeholders a phase may name. Anything else left in a block after
#: substitution is a value the previous phase never produced.
_PR_BRANCH = "pr-branch"


async def _prompt_reaching_execution(workflow: str, phase_id: str) -> str:
    """The prompt the agent is handed, through the round trip production uses."""
    definition = WorkflowDefinition.from_file(_WORKFLOWS / workflow / "workflow.yaml")
    origin = WorkflowTemplateAggregate()
    origin.create_workflow(build_command_from_definition(definition))
    (envelope,) = origin.get_uncommitted_events()
    created = envelope.event
    # THE RESTART PATH: phases come back out of the store as plain JSON, so a
    # hop that loses the prompt survives every in-process test and nothing else.
    rehydrated = WorkflowTemplateAggregate()
    rehydrated.apply_event(type(created).model_validate(created.model_dump(mode="json")))

    captured: list[ExecutablePhase] = []

    class _Processor:
        async def run(
            self,
            *,
            workflow_id: str,
            workflow_name: str,
            phases: list[ExecutablePhase],
            inputs: dict[str, str],
            execution_id: str,
            repos: list[RepositoryRef],
            admitted: object | None = None,
        ) -> WorkflowExecutionResult:
            del workflow_name, inputs, repos, admitted
            captured.extend(phases)
            return WorkflowExecutionResult(
                workflow_id=workflow_id,
                execution_id=execution_id,
                status="completed",
                started_at=datetime.now(UTC),
            )

    class _Repo:
        async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
            return rehydrated if aggregate_id == definition.id else None

    handler = ExecuteWorkflowHandler(
        processor=_Processor(),  # type: ignore[arg-type]
        workflow_repository=_Repo(),  # type: ignore[arg-type]
    )
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=definition.id))

    by_id = {p.phase_id: p for p in captured}
    assert phase_id in by_id, f"{workflow} no longer has a '{phase_id}' phase"
    return by_id[phase_id].prompt_template


@dataclass(frozen=True)
class _Review:
    """A PR waiting to be reviewed, and the workspace a phase would arrive in.

    ``workspace`` is a clone sitting on the default branch with the PR's commit
    fetched but not checked out, which is the state every review phase starts
    from and the state the old prompt never left.
    """

    workspace: Path
    base: str
    head: str
    unrelated: str

    def resolve(self, rev: str) -> str:
        return _git(self.workspace, "rev-parse", rev)

    def move_main(self) -> str:
        """Land an unrelated commit on the base, as the merge queue does."""
        return self._commit_on("main", "queue.txt")

    def move_head(self) -> str:
        """Push another commit to the PR, superseding the recorded head."""
        return self._commit_on(_PR_BRANCH, "amended.txt")

    def _commit_on(self, branch: str, name: str) -> str:
        author = self.workspace.parent / "author"
        _git(author, "checkout", branch)
        (author / name).write_text(name)
        _git(author, "add", name)
        _git(author, "commit", "-m", f"move {branch}")
        _git(author, "push", "origin", branch)
        return _git(author, "rev-parse", "HEAD")


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


_GIT_ENV = {
    "PATH": "/usr/bin:/bin:/usr/local/bin",
    "HOME": "/nonexistent",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _a_pull_request(root: Path) -> _Review:
    origin = root / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        env=_GIT_ENV,
        capture_output=True,
        check=True,
    )
    author = root / "author"
    author.mkdir()
    _git(author, "init", "--initial-branch=main")
    _git(author, "remote", "add", "origin", str(origin))

    (author / "shipped.py").write_text("shipped = 1\n")
    _git(author, "add", "shipped.py")
    _git(author, "commit", "-m", "base")
    _git(author, "push", "origin", "main")
    base = _git(author, "rev-parse", "HEAD")

    # Three distinct commits, so that a gate aimed at the wrong ref resolves to
    # a SHA that is wrong rather than to one that happens to coincide.
    _git(author, "checkout", "-b", _PR_BRANCH)
    (author / "shipped.py").write_text("shipped = 2\n")
    _git(author, "commit", "-am", "the change under review")
    _git(author, "push", "origin", _PR_BRANCH)
    head = _git(author, "rev-parse", "HEAD")

    _git(author, "checkout", "-b", "some-unrelated-branch", "main")
    (author / "elsewhere.py").write_text("elsewhere = 1\n")
    _git(author, "add", "elsewhere.py")
    _git(author, "commit", "-m", "nothing to do with the PR")
    _git(author, "push", "origin", "some-unrelated-branch")
    unrelated = _git(author, "rev-parse", "HEAD")
    _git(author, "checkout", "main")

    workspace = root / "workspace"
    workspace.mkdir()
    _git(workspace, "clone", str(origin), ".")
    return _Review(workspace=workspace, base=base, head=head, unrelated=unrelated)


def _the_script(prompt: str, workflow: str, phase_id: str) -> str:
    blocks = _BASH_BLOCK.findall(prompt)
    assert len(blocks) == 1, (
        f"{workflow} '{phase_id}' has {len(blocks)} fenced `bash` blocks; these tests "
        "run the one that pins the refs, so exactly one may be tagged that way."
    )
    return str(blocks[0])


def _run(script: str, review: _Review, **values: str) -> subprocess.CompletedProcess[str]:
    """Run a phase's block with the recorded values substituted in.

    ``set -e`` is what turns the prompt's ``test`` lines into a gate with an
    exit status. Any placeholder the block names that the caller did not supply
    is a value no earlier phase produces, and is refused here rather than left
    to fail as a mangled git argument.
    """
    for name, value in values.items():
        script = script.replace(f"<{name}>", value)
    leftover = sorted(set(re.findall(r"<[a-z-]+>", script)))
    assert not leftover, (
        f"the block names {leftover}, which no earlier phase produces. "
        f"Substitutable here: {sorted(values)}."
    )
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=review.workspace,
        env={**_GIT_ENV, "HOME": str(review.workspace.parent)},
        capture_output=True,
        text=True,
        check=False,
    )


async def _record_the_refs(workflow: str, review: _Review) -> tuple[str, str]:
    """Run the `investigate` phase's block and read the base and head off it."""
    block = _the_script(
        await _prompt_reaching_execution(workflow, "investigate"), workflow, "investigate"
    )
    recorded = _run(block, review, **{"pr-branch": _PR_BRANCH})
    assert recorded.returncode == 0, recorded.stderr

    shas = _RESOLVED_SHA.findall(recorded.stdout)
    assert len(shas) >= 2, (
        f"{workflow} 'investigate' resolved {shas}, so the SHAs the 'verify' gate "
        f"reads have no producer at all.\n{recorded.stdout}"
    )
    base, head = str(shas[0]), str(shas[1])
    assert (base, head) == (review.base, review.head), (
        f"{workflow} 'investigate' recorded base={base} head={head}; the PR is "
        f"base={review.base} head={review.head}. The next phase checks out the "
        "second of these, so which one comes first is part of the contract."
    )
    return base, head


async def _verify_against(
    workflow: str, review: _Review, base: str, head: str
) -> subprocess.CompletedProcess[str]:
    """Run the `verify` phase's gate on the SHAs `investigate` actually printed."""
    block = _the_script(await _prompt_reaching_execution(workflow, "verify"), workflow, "verify")
    return _run(
        block,
        review,
        **{"pr-branch": _PR_BRANCH, "recorded-base": base, "recorded-head": head},
    )


@pytest.mark.parametrize("workflow", _REVIEW_WORKFLOWS)
async def test_verify_leaves_the_worktree_at_the_recorded_head(
    workflow: str, tmp_path: Path
) -> None:
    """The pin is a commit the tree is ON, not a sentence saying it should be.

    Asserted on the SHA `git rev-parse HEAD` returns, so aiming the gate at any
    other ref - the default branch it arrives on, or a branch with nothing to
    do with the PR - fails here no matter how the prompt words it.

    The base moves first, because that is #1290's own failure: a queue merge
    landing mid-review must cost a line of disclosure and not the run.
    """
    review = _a_pull_request(tmp_path)
    base, head = await _record_the_refs(workflow, review)

    moved = review.move_main()
    assert moved != base

    result = await _verify_against(workflow, review, base, head)

    assert result.returncode == 0, (
        f"{workflow} 'verify' aborted while only `origin/main` had moved "
        f"({base} -> {moved}).\n{result.stdout}\n{result.stderr}"
    )
    assert review.resolve("HEAD") == head, (
        f"{workflow} 'verify' left the workspace at {review.resolve('HEAD')}; the PR "
        f"is {head}. Everything the phase reads after this point - the diff, "
        "the tests it runs, the files it greps - is the wrong code."
    )


@pytest.mark.parametrize("workflow", _REVIEW_WORKFLOWS)
async def test_verify_stops_when_the_head_itself_moved(workflow: str, tmp_path: Path) -> None:
    """Survivable base movement must not become survivable head movement.

    A prompt that dropped the gate would pass the test above - the recorded head
    is still checked out - while certifying a head nobody read.
    """
    review = _a_pull_request(tmp_path)
    base, head = await _record_the_refs(workflow, review)

    superseded = review.move_head()
    assert superseded != head

    result = await _verify_against(workflow, review, base, head)

    assert result.returncode != 0, (
        f"{workflow} 'verify' ran to completion after the PR moved to {superseded}. "
        f"Its findings would describe {head}, which is no longer the PR."
    )


@pytest.mark.parametrize("workflow", _REVIEW_WORKFLOWS)
async def test_the_verdict_names_the_base_it_judged(workflow: str) -> None:
    """Continuing past a moved base is only honest if the verdict says which base.

    The report phase gives the verdict line as a literal block. Before #1290 that
    block named the head alone, which is exactly the silent stale-merge-base the
    issue warns about in the other direction: a reader cannot tell a live
    conflict finding from one made against a base that has since moved.
    """
    prompt = await _prompt_reaching_execution(workflow, "report")

    blocks = _TEXT_BLOCK.findall(prompt)
    assert blocks, f"{workflow} 'report' states no literal verdict line"

    naming_both = [b for b in blocks if "head" in b and "base" in b]

    assert naming_both, (
        f"{workflow} 'report' never requires the verdict to name the base it was "
        f"judged against. Literal blocks found: {blocks!r}"
    )
