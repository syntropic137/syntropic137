"""What a phase's stream hands the shipped ledger, and what it does not."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_domain.contexts.orchestration._shared.shipped_ledger import (
    CommitShipped,
    ExecutionAttribution,
    PullRequestMerged,
    PullRequestOpened,
)
from syn_domain.contexts.orchestration._shared.shipped_recorder import ShippedRecorder

AT = datetime(2026, 10, 9, 12, tzinfo=UTC)
URL = "https://github.com/acme/api/pull/42"


class _Ledger:
    def __init__(self) -> None:
        self.commits: list[CommitShipped] = []
        self.prs: list[PullRequestOpened] = []
        self.fail = False

    async def record_commit(self, commit: CommitShipped) -> None:
        if self.fail:
            raise RuntimeError("down")
        self.commits.append(commit)

    async def record_pull_request_opened(self, pr: PullRequestOpened) -> None:
        self.prs.append(pr)

    async def record_pull_request_merged(self, merge: PullRequestMerged) -> None: ...

    async def daily(self, *_: object) -> list[object]:
        return []


def _recorder(
    ledger: _Ledger, repos: tuple[str, ...] = ("acme/api", "acme/web")
) -> ShippedRecorder:
    attribution = ExecutionAttribution("exec-1", "wf-1", "Implement", repos)
    return ShippedRecorder(ledger=ledger, attribution=attribution, clock=lambda: AT)


@pytest.mark.unit
class TestCommits:
    @pytest.mark.asyncio
    async def test_attributed_to_the_repo_cloned_under_that_directory(self) -> None:
        ledger = _Ledger()
        await _recorder(ledger).commit_seen("abc", "web")
        assert [(c.sha, c.repository, c.workflow_id, c.execution_id) for c in ledger.commits] == [
            ("abc", "acme/web", "wf-1", "exec-1")
        ]

    @pytest.mark.asyncio
    async def test_unattributable_commits_are_not_recorded(self) -> None:
        ledger = _Ledger()
        recorder = _recorder(ledger)
        await recorder.commit_seen(None, "web")
        await recorder.commit_seen("abc", "unknown-dir")
        await recorder.commit_seen("abc", None)  # two repos: which one?
        assert ledger.commits == []

    @pytest.mark.asyncio
    async def test_a_single_repo_run_owns_an_unnamed_commit(self) -> None:
        ledger = _Ledger()
        await _recorder(ledger, ("acme/api",)).commit_seen("abc", None)
        assert ledger.commits[0].repository == "acme/api"

    @pytest.mark.asyncio
    async def test_a_ledger_failure_never_reaches_the_phase(self) -> None:
        ledger = _Ledger()
        ledger.fail = True
        await _recorder(ledger).commit_seen("abc", "api")


@pytest.mark.unit
class TestPullRequests:
    @pytest.mark.asyncio
    async def test_a_successful_gh_pr_create_records_its_pr(self) -> None:
        ledger = _Ledger()
        recorder = _recorder(ledger)
        recorder.command_started("t1", "git push && gh pr create --fill")
        await recorder.command_finished("t1", True, f"Creating pull request\n{URL}\n")
        assert [(p.repository, p.number, p.url, p.created_at) for p in ledger.prs] == [
            ("acme/api", 42, URL, AT)
        ]

    @pytest.mark.parametrize(
        ("command", "success", "output"),
        [
            ("gh pr create --fill", False, URL),
            ("gh pr create --dry-run", True, URL),
            ("echo 'gh pr create'", True, URL),
            ("gh pr view 42", True, URL),
            ("gh pr create --fill", True, f"{URL}\nfollow-up text"),
        ],
    )
    @pytest.mark.asyncio
    async def test_nothing_else_does(self, command: str, success: bool, output: str) -> None:
        ledger = _Ledger()
        recorder = _recorder(ledger)
        recorder.command_started("t1", command)
        await recorder.command_finished("t1", success, output)
        assert ledger.prs == []

    @pytest.mark.asyncio
    async def test_a_result_without_its_start_is_ignored(self) -> None:
        ledger = _Ledger()
        await _recorder(ledger).command_finished("never-started", True, URL)
        assert ledger.prs == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_one_call_creating_two_prs_records_both() -> None:
    ledger = _Ledger()
    recorder = _recorder(ledger)
    recorder.command_started(
        "t1", "gh pr create -R acme/api --fill && gh pr create -R acme/web --fill"
    )
    await recorder.command_finished(
        "t1", True, "https://github.com/acme/api/pull/1\nhttps://github.com/acme/web/pull/2\n"
    )
    assert [(p.repository, p.number) for p in ledger.prs] == [("acme/api", 1), ("acme/web", 2)]
