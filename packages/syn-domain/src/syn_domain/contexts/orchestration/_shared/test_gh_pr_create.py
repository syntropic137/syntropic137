"""A PR is created by a run only on a successful, real `gh pr create`."""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.gh_pr_create import (
    CreatedPullRequest,
    created_pull_requests,
    is_gh_pr_create,
)

URL = "https://github.com/acme/api/pull/42"
PR = CreatedPullRequest("acme/api", 42, URL)


@pytest.mark.unit
class TestTheCommandMustRunGhPrCreate:
    @pytest.mark.parametrize(
        "command",
        [
            "gh pr create --fill",
            "cd /workspace/api && gh pr create --title t --body 'a; b | c && d'",
            "git push -u origin feat && gh pr create --fill",
            "GH_TOKEN=x gh pr create --fill",
            "env FOO=1 gh pr create --fill",
            "git push\ngh pr create --fill",
            "printf 'body' | gh pr create --body-file -",
            "/bin/bash -lc 'git push && gh pr create --fill'",
        ],
    )
    def test_accepted(self, command: str) -> None:
        assert is_gh_pr_create(command)

    @pytest.mark.parametrize(
        "command",
        [
            "echo 'gh pr create'",
            'echo "gh pr create"; echo https://github.com/acme/api/pull/42',
            "echo gh pr create",
            "printf '%s' \"gh pr create --fill\"",
            "gh pr create --dry-run --fill",
            "gh pr create --fill --dry-run",
            "gh pr view 42",
            "gh pr list",
            "gh pr create 'unclosed",
            "# gh pr create",
            "",
        ],
    )
    def test_rejected(self, command: str) -> None:
        assert not is_gh_pr_create(command)


@pytest.mark.unit
class TestTheCreateMustBeWhatProducedTheUrl:
    """Exit 0 is the LAST command's: the create must be last, or it proved nothing."""

    @pytest.mark.parametrize(
        "command",
        [
            f"gh pr create --fill || echo {URL}",
            f"false && gh pr create --fill; echo {URL}",
            f"gh pr create --fill; echo {URL}",
            "gh pr create --fill | tee out.txt",
            "gh pr create --fill &",
            "if true; then gh pr create --fill; fi",
            "gh pr create --fill && echo done",
        ],
    )
    def test_a_create_that_is_not_last_creates_nothing(self, command: str) -> None:
        assert created_pull_requests(command, True, URL) == []

    @pytest.mark.parametrize(
        "command",
        [
            "git push -u origin feat && gh pr create --fill",
            "git push; gh pr create --fill",
            "printf body | gh pr create --body-file -",
            "(gh pr create --fill)",
            "gh pr create --fill;",
        ],
    )
    def test_a_create_that_is_last_owns_the_exit_status(self, command: str) -> None:
        assert created_pull_requests(command, True, URL) == [PR]

    def test_a_chain_of_creates_records_every_pr(self) -> None:
        command = "gh pr create -R acme/api --fill && gh pr create -R acme/web --fill"
        output = (
            "https://github.com/acme/api/pull/41\nwarning: x\nhttps://github.com/acme/web/pull/9"
        )
        assert [(p.repository, p.number) for p in created_pull_requests(command, True, output)] == [
            ("acme/api", 41),
            ("acme/web", 9),
        ]


@pytest.mark.unit
class TestTheOutputMustEndInTheCreatedPrsUrl:
    def test_success_and_url_as_the_last_line(self) -> None:
        output = f"Warning: 2 uncommitted changes\n\nCreating pull request\n{URL}\n"
        assert created_pull_requests("gh pr create --fill", True, output) == [PR]

    def test_a_failed_command_creates_nothing_even_with_a_url(self) -> None:
        output = f"a pull request for branch already exists:\n{URL}"
        assert created_pull_requests("gh pr create --fill", False, output) == []

    def test_a_dry_run_creates_nothing(self) -> None:
        assert created_pull_requests("gh pr create --dry-run", True, URL) == []

    def test_quoted_command_text_creates_nothing(self) -> None:
        command = "echo 'gh pr create'; echo " + URL
        assert created_pull_requests(command, True, f"gh pr create\n{URL}") == []

    @pytest.mark.parametrize(
        "output",
        [
            f"{URL}\nsomething after",
            f"see {URL}",
            "https://github.com/acme/api/pull/42/files",
            "https://github.com/acme/api/issues/42",
            "",
        ],
    )
    def test_the_url_must_be_exactly_the_last_line(self, output: str) -> None:
        assert created_pull_requests("gh pr create --fill", True, output) == []

    def test_only_the_last_of_several_urls_is_the_created_pr(self) -> None:
        output = "https://github.com/acme/api/pull/7\nhttps://github.com/acme/api/pull/42"
        assert created_pull_requests("gh pr create --fill", True, output) == [PR]
