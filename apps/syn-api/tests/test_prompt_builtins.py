"""Tests for built-in template variable substitution in workspace prompts.

Covers ``{{execution_id}}``, ``{{workflow_id}}``, ``{{repo_url}}``, and
``{{repository}}`` -- the last of which is derived from ``repo_url`` so legacy
single-repo workflows can keep the familiar ``{{repository}}`` placeholder
after the v0.25.2 ADR-063 migration drops it from input declarations.
"""

from __future__ import annotations

import pytest

from syn_api._wiring import _owner_repo_from_url, _substitute_builtins


@pytest.mark.unit
class TestOwnerRepoFromUrl:
    def test_https_url_returns_owner_repo(self) -> None:
        assert _owner_repo_from_url("https://github.com/acme/widgets") == "acme/widgets"

    def test_trailing_slash_stripped(self) -> None:
        assert _owner_repo_from_url("https://github.com/acme/widgets/") == "acme/widgets"

    def test_dot_git_suffix_stripped(self) -> None:
        assert _owner_repo_from_url("https://github.com/acme/widgets.git") == "acme/widgets"

    def test_none_returns_empty(self) -> None:
        assert _owner_repo_from_url(None) == ""

    def test_empty_string_returns_empty(self) -> None:
        assert _owner_repo_from_url("") == ""

    def test_non_github_url_returns_empty(self) -> None:
        assert _owner_repo_from_url("https://gitlab.com/acme/widgets") == ""


@pytest.mark.unit
class TestSubstituteBuiltins:
    def test_repository_substituted_from_repo_url(self) -> None:
        result = _substitute_builtins(
            "review {{repository}}#{{repo_url}}",
            execution_id="exec-1",
            workflow_id="wf-1",
            repo_url="https://github.com/acme/widgets",
        )
        assert "acme/widgets" in result
        assert "https://github.com/acme/widgets" in result
        assert "{{repository}}" not in result

    def test_repository_empty_when_no_repo_url(self) -> None:
        result = _substitute_builtins(
            "repo={{repository}}",
            execution_id="exec-1",
            workflow_id="wf-1",
            repo_url=None,
        )
        assert result == "repo="

    def test_all_builtins_replaced(self) -> None:
        result = _substitute_builtins(
            "x={{execution_id}} y={{workflow_id}} z={{repository}}",
            execution_id="exec-1",
            workflow_id="wf-1",
            repo_url="https://github.com/o/r",
        )
        assert result == "x=exec-1 y=wf-1 z=o/r"
