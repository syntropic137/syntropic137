"""Tests for GitHub App repo pre-validation in execute workflow endpoint (#598)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.routes.executions.commands import (
    _parse_repo_from_url,
    _resolve_target_repo,
    _validate_repo_access,
)

# -- _parse_repo_from_url tests -----------------------------------------------


class TestParseRepoFromUrl:
    def test_github_https_url(self) -> None:
        assert _parse_repo_from_url("https://github.com/owner/repo") == "owner/repo"

    def test_trailing_slash(self) -> None:
        assert _parse_repo_from_url("https://github.com/owner/repo/") == "owner/repo"

    def test_none(self) -> None:
        assert _parse_repo_from_url(None) is None

    def test_empty_string(self) -> None:
        assert _parse_repo_from_url("") is None

    def test_no_slash(self) -> None:
        assert _parse_repo_from_url("skip") is None

    def test_short_path(self) -> None:
        assert _parse_repo_from_url("owner/repo") == "owner/repo"


# -- _resolve_target_repo tests ------------------------------------------------


class TestResolveTargetRepo:
    @staticmethod
    def _make_workflow(
        repo_url: str | None = None,
        input_declarations: list[object] | None = None,
    ) -> MagicMock:
        wf = MagicMock()
        wf._repository_url = repo_url
        wf.input_declarations = input_declarations or []
        return wf

    def test_returns_none_when_no_repo_url(self) -> None:
        wf = self._make_workflow(repo_url=None)
        assert _resolve_target_repo(wf, {}, None) is None

    def test_resolves_simple_url(self) -> None:
        wf = self._make_workflow(repo_url="https://github.com/org/myrepo")
        assert _resolve_target_repo(wf, {}, None) == "org/myrepo"

    def test_resolves_placeholders_from_inputs(self) -> None:
        wf = self._make_workflow(repo_url="https://github.com/{{owner}}/{{repo}}")
        result = _resolve_target_repo(wf, {"owner": "acme", "repo": "app"}, None)
        assert result == "acme/app"

    def test_returns_none_when_placeholders_unresolved(self) -> None:
        wf = self._make_workflow(repo_url="https://github.com/{{owner}}/repo")
        assert _resolve_target_repo(wf, {}, None) is None

    def test_merges_task_into_placeholders(self) -> None:
        wf = self._make_workflow(repo_url="https://github.com/org/{{task}}")
        assert _resolve_target_repo(wf, {}, "myrepo") == "org/myrepo"


# -- _validate_repo_access tests -----------------------------------------------


@pytest.mark.asyncio
async def test_validate_skips_when_github_app_not_configured() -> None:
    """No-op when GitHub App is not configured."""
    mock_settings = MagicMock()
    mock_settings.is_configured = False

    with patch(
        "syn_shared.settings.github.GitHubAppSettings",
        return_value=mock_settings,
    ):
        await _validate_repo_access("owner/repo")


@pytest.mark.asyncio
async def test_validate_raises_422_when_app_not_installed() -> None:
    """Returns 422 when GitHub App is not installed on the target repo."""
    from fastapi import HTTPException

    from syn_adapters.github.client import GitHubAuthError

    mock_settings = MagicMock()
    mock_settings.is_configured = True

    mock_client = MagicMock()
    mock_client.get_installation_for_repo = AsyncMock(
        side_effect=GitHubAuthError("GitHub App not installed on repository: owner/repo")
    )

    with (
        patch(
            "syn_shared.settings.github.GitHubAppSettings",
            return_value=mock_settings,
        ),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _validate_repo_access("owner/repo")

    assert exc_info.value.status_code == 422
    assert "GitHub App not installed" in str(exc_info.value.detail)
    assert "owner/repo" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_validate_raises_422_with_generic_auth_error() -> None:
    """Other GitHubAuthErrors surface the original message."""
    from fastapi import HTTPException

    from syn_adapters.github.client import GitHubAuthError

    mock_settings = MagicMock()
    mock_settings.is_configured = True

    mock_client = MagicMock()
    mock_client.get_installation_for_repo = AsyncMock(
        side_effect=GitHubAuthError("Invalid private key")
    )

    with (
        patch(
            "syn_shared.settings.github.GitHubAppSettings",
            return_value=mock_settings,
        ),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _validate_repo_access("owner/repo")

    assert exc_info.value.status_code == 422
    assert "authentication failed" in str(exc_info.value.detail).lower()
    assert "Invalid private key" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_validate_proceeds_on_transient_error() -> None:
    """Transient errors (network, etc.) log warning but don't block execution."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    mock_client = MagicMock()
    mock_client.get_installation_for_repo = AsyncMock(
        side_effect=ConnectionError("network timeout")
    )

    with (
        patch(
            "syn_shared.settings.github.GitHubAppSettings",
            return_value=mock_settings,
        ),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        await _validate_repo_access("owner/repo")


@pytest.mark.asyncio
async def test_validate_succeeds_when_app_installed() -> None:
    """No error when GitHub App is installed on the target repo."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    mock_client = MagicMock()
    mock_client.get_installation_for_repo = AsyncMock(return_value="12345")

    with (
        patch(
            "syn_shared.settings.github.GitHubAppSettings",
            return_value=mock_settings,
        ),
        patch(
            "syn_adapters.github.client.get_github_client",
            return_value=mock_client,
        ),
    ):
        await _validate_repo_access("owner/repo")


# -- requires_repos preflight gating (ADR-058 #666) ---------------------------


class TestRequiresReposPreflightGating:
    """Regression tests: workflows with requires_repos=False skip repo validation."""

    @staticmethod
    def _make_workflow(
        repo_url: str = "",
        requires_repos: bool = True,
        input_declarations: list[object] | None = None,
        repos: list[str] | None = None,
    ) -> MagicMock:
        wf = MagicMock()
        wf._repository_url = repo_url
        wf.requires_repos = requires_repos
        wf.input_declarations = input_declarations or []
        wf.repos = repos or []
        return wf

    def test_no_repo_workflow_skips_placeholder_check(self) -> None:
        """requires_repos=False should not call _check_repo_url_placeholders."""
        from syn_api.routes.executions.commands import (
            _check_missing_declarations,
            _merge_inputs,
        )

        wf = self._make_workflow(repo_url="", requires_repos=False)
        merged = _merge_inputs(wf, {}, None)
        _check_missing_declarations(wf, merged)
        # This should NOT raise even though repo_url is empty
        # With requires_repos=True, a placeholder URL would trigger validation
        # With requires_repos=False, this block is never reached in the endpoint

    def test_repo_url_placeholder_raises_when_repos_required(self) -> None:
        """requires_repos=True should raise on unresolved placeholders."""
        from fastapi import HTTPException

        from syn_api.routes.executions.commands import (
            _check_repo_url_placeholders,
            _merge_inputs,
        )

        wf = self._make_workflow(
            repo_url="https://github.com/{{owner}}/{{repo}}",
            requires_repos=True,
        )
        merged = _merge_inputs(wf, {}, None)
        with pytest.raises(HTTPException) as exc_info:
            _check_repo_url_placeholders(wf, merged)
        assert exc_info.value.status_code == 422
        assert "owner" in str(exc_info.value.detail)

    def test_get_preflight_repos_empty_when_no_repo(self) -> None:
        """No preflight repos when workflow has no repo URL and no repos list."""
        from syn_api.routes.executions.commands import _get_preflight_repos

        wf = self._make_workflow(repo_url="", requires_repos=False)
        repos = _get_preflight_repos([], {}, wf, None)
        assert repos == []

    def test_get_preflight_repos_uses_typed_repos(self) -> None:
        """Typed RepositoryRef list flows directly into preflight URLs (no CSV detour)."""
        from syn_api.routes.executions.commands import _get_preflight_repos
        from syn_domain.contexts._shared.repository_ref import RepositoryRef

        wf = self._make_workflow(repo_url="", requires_repos=True)
        typed = [
            RepositoryRef.from_slug("owner/a"),
            RepositoryRef.from_url("https://github.com/owner/b"),
        ]
        repos = _get_preflight_repos(typed, {}, wf, None)
        assert repos == [
            "https://github.com/owner/a",
            "https://github.com/owner/b",
        ]

    @pytest.mark.asyncio
    async def test_validate_all_repos_noop_on_empty_list(self) -> None:
        """_validate_all_repos_access with empty list should be a no-op."""
        from syn_api.routes.executions.commands import _validate_all_repos_access

        # Should complete without error or any GitHub API calls
        await _validate_all_repos_access([])

    def test_check_missing_declarations_always_runs(self) -> None:
        """Required input declarations are checked even with requires_repos=False."""
        from fastapi import HTTPException

        from syn_api.routes.executions.commands import (
            _check_missing_declarations,
            _merge_inputs,
        )

        decl = MagicMock()
        decl.name = "task"
        decl.required = True
        decl.default = None

        wf = self._make_workflow(
            repo_url="",
            requires_repos=False,
            input_declarations=[decl],
        )
        merged = _merge_inputs(wf, {}, None)
        with pytest.raises(HTTPException) as exc_info:
            _check_missing_declarations(wf, merged)
        assert exc_info.value.status_code == 422
        assert "task" in str(exc_info.value.detail)


# -- Reserved repo input-key rejection (ADR-063 boundary) ---------------------


class TestReservedRepoInputKeyRejection:
    """'repository' and 'repos' as input keys are rejected at the HTTP boundary.

    Regression: CLI used to send --input repository=X as a generic input, API
    returned 200 + BackgroundTask, handler's _resolve_repos raised ValueError
    inside the task. The silent-success-then-404 is fixed by synchronous 422.
    """

    @pytest.mark.asyncio
    async def test_rejects_singular_repository_input_key(self) -> None:
        from fastapi import HTTPException

        from syn_api.routes.executions.commands import (
            ExecuteWorkflowRequest,
            _validate_execution_request,
        )

        wf = MagicMock()
        wf.requires_repos = True
        wf.input_declarations = []

        with (
            patch(
                "syn_api.routes.executions.commands.get_workflow_repo",
                return_value=MagicMock(get_by_id=AsyncMock(return_value=wf)),
            ),
            patch(
                "syn_api.routes.executions.commands.ensure_connected",
                new=AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _validate_execution_request(
                "wf-1",
                ExecuteWorkflowRequest(inputs={"repository": "owner/repo"}, repos=[]),
            )

        assert exc_info.value.status_code == 422
        detail = str(exc_info.value.detail)
        assert "'repository'" in detail
        assert "-R" in detail

    @pytest.mark.asyncio
    async def test_rejects_plural_repos_input_key(self) -> None:
        from fastapi import HTTPException

        from syn_api.routes.executions.commands import (
            ExecuteWorkflowRequest,
            _validate_execution_request,
        )

        wf = MagicMock()
        wf.requires_repos = True
        wf.input_declarations = []

        with (
            patch(
                "syn_api.routes.executions.commands.get_workflow_repo",
                return_value=MagicMock(get_by_id=AsyncMock(return_value=wf)),
            ),
            patch(
                "syn_api.routes.executions.commands.ensure_connected",
                new=AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _validate_execution_request(
                "wf-1",
                ExecuteWorkflowRequest(inputs={"repos": "owner/a,owner/b"}, repos=[]),
            )

        assert exc_info.value.status_code == 422
        assert "'repos'" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_typed_repos_field_is_accepted(self) -> None:
        """The typed `repos: list[str]` field is the canonical channel — no rejection.

        ADR-063: typed repos do NOT leak back into ``effective_inputs`` as a CSV
        string. Repository identity travels as ``RepositoryRef`` end-to-end.
        """
        from syn_api.routes.executions.commands import (
            ExecuteWorkflowRequest,
            _validate_execution_request,
        )

        wf = MagicMock()
        wf.requires_repos = False
        wf.input_declarations = []
        wf.repos = []
        wf._repository_url = ""

        with (
            patch(
                "syn_api.routes.executions.commands.get_workflow_repo",
                return_value=MagicMock(get_by_id=AsyncMock(return_value=wf)),
            ),
            patch(
                "syn_api.routes.executions.commands.ensure_connected",
                new=AsyncMock(),
            ),
        ):
            _, effective_inputs, typed_repos = await _validate_execution_request(
                "wf-1",
                ExecuteWorkflowRequest(
                    inputs={},
                    repos=["https://github.com/owner/a", "owner/b"],
                ),
            )

        assert len(typed_repos) == 2
        assert typed_repos[0].https_url == "https://github.com/owner/a"
        assert typed_repos[1].https_url == "https://github.com/owner/b"
        assert "repos" not in effective_inputs
        assert "repository" not in effective_inputs
