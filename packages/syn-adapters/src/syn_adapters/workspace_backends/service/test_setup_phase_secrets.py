"""Unit tests for SetupPhaseSecrets (ADR-058, ISS-196).

Tests multi-repo token resolution, build_setup_script() generation,
and edge cases for the workspace hydration feature.

Run: pytest -m unit packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_setup_phase_secrets.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service.setup_phase_secrets import (
    DEFAULT_SETUP_SCRIPT,
    SetupPhaseSecrets,
    _repo_dir_name,
    _repo_full_name,
)

# =============================================================================
# _repo_dir_name / _repo_full_name helpers
# =============================================================================


@pytest.mark.unit
class TestRepoNameExtraction:
    """Tests for _repo_dir_name and _repo_full_name helpers."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://github.com/org/repo-a.git", "org__repo-a"),
            ("https://github.com/org/repo-b/", "org__repo-b"),
            ("https://github.com/org/repo-c", "org__repo-c"),
            ("https://github.com/org/my.repo.git", "org__my.repo"),
        ],
    )
    def test_repo_dir_name(self, url: str, expected: str) -> None:
        assert _repo_dir_name(url) == expected

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://github.com/org/repo-a.git", "org/repo-a"),
            ("https://github.com/org/repo-b/", "org/repo-b"),
            ("https://github.com/org/repo-c", "org/repo-c"),
        ],
    )
    def test_repo_full_name(self, url: str, expected: str) -> None:
        assert _repo_full_name(url) == expected


# =============================================================================
# build_setup_script
# =============================================================================


@pytest.mark.unit
class TestBuildSetupScript:
    """Tests for SetupPhaseSecrets.build_setup_script()."""

    def test_no_repos_returns_default_script(self) -> None:
        """When no repositories configured, returns DEFAULT_SETUP_SCRIPT unchanged."""
        secrets = SetupPhaseSecrets()
        assert secrets.build_setup_script() == DEFAULT_SETUP_SCRIPT

    def test_single_repo_contains_git_clone(self) -> None:
        """Single repo produces a git clone line."""
        secrets = SetupPhaseSecrets(
            repositories=["https://github.com/org/repo-a"],
            repo_tokens={"https://github.com/org/repo-a": "tok-abc"},
        )
        script = secrets.build_setup_script()
        assert "git clone" in script
        assert "/workspace/repos/org__repo-a" in script
        assert "mkdir -p /workspace/repos" in script

    def test_single_repo_contains_credential_entry(self) -> None:
        """Single repo writes per-repo git credential entry."""
        secrets = SetupPhaseSecrets(
            repositories=["https://github.com/org/repo-a"],
            repo_tokens={"https://github.com/org/repo-a": "tok-abc"},
        )
        script = secrets.build_setup_script()
        assert "x-access-token:tok-abc@github.com/org/repo-a" in script
        assert "~/.git-credentials" in script
        assert "chmod 600 ~/.git-credentials" in script

    def test_multi_repo_has_multiple_clone_lines(self) -> None:
        """Multiple repos produce one clone line per repo."""
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/org/repo-a",
                "https://github.com/org/repo-b",
            ],
            repo_tokens={
                "https://github.com/org/repo-a": "tok-a",
                "https://github.com/org/repo-b": "tok-b",
            },
        )
        script = secrets.build_setup_script()
        assert script.count("git clone") == 2
        assert "/workspace/repos/org__repo-a" in script
        assert "/workspace/repos/org__repo-b" in script

    def test_multi_repo_has_multiple_credential_lines(self) -> None:
        """Multiple repos each get their own credential entry."""
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/org/repo-a",
                "https://github.com/org/repo-b",
            ],
            repo_tokens={
                "https://github.com/org/repo-a": "tok-a",
                "https://github.com/org/repo-b": "tok-b",
            },
        )
        script = secrets.build_setup_script()
        assert "x-access-token:tok-a@github.com/org/repo-a" in script
        assert "x-access-token:tok-b@github.com/org/repo-b" in script

    def test_idempotency_guard_on_each_clone(self) -> None:
        """Each clone line has an idempotency guard."""
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/org/repo-a",
                "https://github.com/org/repo-b",
            ],
            repo_tokens={},
        )
        script = secrets.build_setup_script()
        # Both guards must be present
        assert '[ -d "/workspace/repos/org__repo-a" ] ||' in script
        assert '[ -d "/workspace/repos/org__repo-b" ] ||' in script

    def test_repos_without_tokens_no_credential_lines(self) -> None:
        """Repos with empty repo_tokens get clone lines but no credential block."""
        secrets = SetupPhaseSecrets(
            repositories=["https://github.com/org/repo-a"],
            repo_tokens={},
        )
        script = secrets.build_setup_script()
        assert "git clone" in script
        assert "x-access-token" not in script
        assert "~/.git-credentials" not in script

    def test_gh_cli_configured_with_first_token(self) -> None:
        """gh CLI hosts.yml is written using the first repo's token."""
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/org/repo-a",
                "https://github.com/org/repo-b",
            ],
            repo_tokens={
                "https://github.com/org/repo-a": "tok-first",
                "https://github.com/org/repo-b": "tok-second",
            },
        )
        script = secrets.build_setup_script()
        assert "~/.config/gh/hosts.yml" in script
        assert "tok-first" in script


# =============================================================================
# SetupPhaseSecrets.create() — multi-installation token resolution
# =============================================================================


@pytest.mark.unit
class TestSetupPhaseSecretsCreate:
    """Tests for SetupPhaseSecrets.create() multi-installation resolution."""

    @pytest.mark.anyio
    async def test_no_repos_skips_github(self) -> None:
        """Empty repositories list skips GitHub API entirely."""
        with patch(
            "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_claude_credentials",
            return_value=(None, None),
        ):
            secrets = await SetupPhaseSecrets.create(repositories=[], require_github=False)

        assert secrets.repo_tokens == {}
        assert secrets.repositories == []

    @pytest.mark.anyio
    async def test_single_installation_single_token_call(self) -> None:
        """Two repos from same installation → one get_installation_token call."""
        mock_client = AsyncMock()
        mock_client.get_installation_for_repo.return_value = "inst-1"
        mock_client.get_installation_token.return_value = "tok-inst1"

        repos = [
            "https://github.com/org/repo-a",
            "https://github.com/org/repo-b",
        ]

        with (
            patch(
                "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_claude_credentials",
                return_value=(None, None),
            ),
            patch("syn_shared.settings.github.GitHubAppSettings") as MockSettings,
            patch(
                "syn_adapters.github.GitHubAppClient",
                return_value=mock_client,
            ),
        ):
            MockSettings.return_value.is_configured = True
            MockSettings.return_value.bot_name = "syn-bot"
            MockSettings.return_value.bot_email = "syn-bot@users.noreply.github.com"
            secrets = await SetupPhaseSecrets.create(repositories=repos, require_github=True)

        # One token minted despite two repos
        mock_client.get_installation_token.assert_called_once_with("inst-1")
        assert secrets.repo_tokens[repos[0]] == "tok-inst1"
        assert secrets.repo_tokens[repos[1]] == "tok-inst1"

    @pytest.mark.anyio
    async def test_multi_installation_two_token_calls(self) -> None:
        """Repos from different installations → separate token per installation."""
        repo_a = "https://github.com/org-a/repo-a"
        repo_b = "https://github.com/org-b/repo-b"

        async def fake_get_installation(full_name: str) -> str:
            return "inst-a" if "org-a" in full_name else "inst-b"

        mock_client = AsyncMock()
        mock_client.get_installation_for_repo.side_effect = fake_get_installation
        mock_client.get_installation_token.side_effect = lambda inst_id: (
            "tok-a" if inst_id == "inst-a" else "tok-b"
        )

        with (
            patch(
                "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_claude_credentials",
                return_value=(None, None),
            ),
            patch("syn_shared.settings.github.GitHubAppSettings") as MockSettings,
            patch(
                "syn_adapters.github.GitHubAppClient",
                return_value=mock_client,
            ),
        ):
            MockSettings.return_value.is_configured = True
            MockSettings.return_value.bot_name = "syn-bot"
            MockSettings.return_value.bot_email = "syn-bot@users.noreply.github.com"
            secrets = await SetupPhaseSecrets.create(
                repositories=[repo_a, repo_b], require_github=True
            )

        assert mock_client.get_installation_token.call_count == 2
        assert secrets.repo_tokens[repo_a] == "tok-a"
        assert secrets.repo_tokens[repo_b] == "tok-b"

    @pytest.mark.anyio
    async def test_fails_fast_on_installation_lookup_error(self) -> None:
        """Installation lookup failure propagates immediately (fail-fast)."""
        mock_client = AsyncMock()
        mock_client.get_installation_for_repo.side_effect = Exception(
            "404: Repo not in any installation"
        )

        with (
            patch(
                "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_claude_credentials",
                return_value=(None, None),
            ),
            patch("syn_shared.settings.github.GitHubAppSettings") as MockSettings,
            patch(
                "syn_adapters.github.GitHubAppClient",
                return_value=mock_client,
            ),
        ):
            MockSettings.return_value.is_configured = True
            MockSettings.return_value.bot_name = "syn-bot"
            MockSettings.return_value.bot_email = "syn-bot@users.noreply.github.com"
            with pytest.raises(Exception, match="404"):
                await SetupPhaseSecrets.create(
                    repositories=["https://github.com/org/private-repo"],
                    require_github=True,
                )

        mock_client.get_installation_token.assert_not_called()

    @pytest.mark.anyio
    async def test_require_github_false_swallows_lookup_error(self) -> None:
        """require_github=False skips token on lookup failure (no exception)."""
        mock_client = AsyncMock()
        mock_client.get_installation_for_repo.side_effect = Exception("not installed")

        with (
            patch(
                "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_claude_credentials",
                return_value=(None, None),
            ),
            patch("syn_shared.settings.github.GitHubAppSettings") as MockSettings,
            patch(
                "syn_adapters.github.GitHubAppClient",
                return_value=mock_client,
            ),
        ):
            MockSettings.return_value.is_configured = True
            MockSettings.return_value.bot_name = "syn-bot"
            MockSettings.return_value.bot_email = "syn-bot@users.noreply.github.com"
            secrets = await SetupPhaseSecrets.create(
                repositories=["https://github.com/org/public-repo"],
                require_github=False,
            )

        # No token fetched, but no exception
        assert secrets.repo_tokens == {}

    @pytest.mark.anyio
    async def test_github_app_not_configured_raises_when_required(self) -> None:
        """GitHubAppNotConfiguredError raised when require_github=True and App not configured."""
        from syn_adapters.workspace_backends.service.setup_phase_secrets import (
            GitHubAppNotConfiguredError,
        )

        with (
            patch(
                "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_claude_credentials",
                return_value=(None, None),
            ),
            patch("syn_shared.settings.github.GitHubAppSettings") as MockSettings,
        ):
            MockSettings.return_value.is_configured = False
            with pytest.raises(GitHubAppNotConfiguredError):
                await SetupPhaseSecrets.create(
                    repositories=["https://github.com/org/repo"],
                    require_github=True,
                )


# =============================================================================
# Claude credential resolution
# =============================================================================


@pytest.mark.unit
class TestClaudeCredentialResolution:
    """Tests for _resolve_claude_credentials dual-credential behaviour."""

    def test_both_set_oauth_wins_and_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """When both OAuth token and API key are set, OAuth wins and a warning is logged."""
        import logging

        from syn_adapters.workspace_backends.service.setup_phase_secrets import (
            _resolve_claude_credentials,
        )

        with patch("syn_shared.settings.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.claude_code_oauth_token = MagicMock()
            mock_settings.claude_code_oauth_token.get_secret_value.return_value = "oauth-token-123"
            mock_settings.anthropic_api_key = MagicMock()
            mock_settings.anthropic_api_key.get_secret_value.return_value = "api-key-456"
            mock_get_settings.return_value = mock_settings

            with caplog.at_level(logging.WARNING):
                oauth_token, api_key = _resolve_claude_credentials()

        assert oauth_token == "oauth-token-123"
        assert api_key == "api-key-456"
        assert any("CLAUDE_CODE_OAUTH_TOKEN" in record.message for record in caplog.records)
