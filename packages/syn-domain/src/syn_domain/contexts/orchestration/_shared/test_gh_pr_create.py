"""A PR is created by a run only on a successful, real `gh pr create`."""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.gh_pr_create import (
    CreatedPullRequest,
    created_pull_request,
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
class TestTheOutputMustEndInTheCreatedPrsUrl:
    def test_success_and_url_as_the_last_line(self) -> None:
        output = f"Warning: 2 uncommitted changes\n\nCreating pull request\n{URL}\n"
        assert created_pull_request("gh pr create --fill", True, output) == PR

    def test_a_failed_command_creates_nothing_even_with_a_url(self) -> None:
        output = f"a pull request for branch already exists:\n{URL}"
        assert created_pull_request("gh pr create --fill", False, output) is None

    def test_a_dry_run_creates_nothing(self) -> None:
        assert created_pull_request("gh pr create --dry-run", True, URL) is None

    def test_quoted_command_text_creates_nothing(self) -> None:
        command = "echo 'gh pr create'; echo " + URL
        assert created_pull_request(command, True, f"gh pr create\n{URL}") is None

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
        assert created_pull_request("gh pr create --fill", True, output) is None

    def test_only_the_last_of_several_urls_is_the_created_pr(self) -> None:
        output = "https://github.com/acme/api/pull/7\nhttps://github.com/acme/api/pull/42"
        assert created_pull_request("gh pr create --fill", True, output) == PR
