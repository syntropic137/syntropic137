"""Unit tests for SetupPhaseSecrets (ADR-058, ISS-196).

Tests multi-repo token resolution, build_setup_script() generation,
and edge cases for the workspace hydration feature.

Run: pytest -m unit packages/syn-adapters/src/syn_adapters/workspace_backends/service/test_setup_phase_secrets.py -v
"""

from __future__ import annotations

import shlex
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service.setup_phase_secrets import (
    DEFAULT_SETUP_SCRIPT,
    RepoNameCollisionError,
    SetupPhaseSecrets,
    _repo_full_name,
    _repo_name,
)

# =============================================================================
# _repo_name / _repo_full_name helpers
# =============================================================================


# Marked at module scope: these files were never COLLECTED before the
# testpaths change in this commit, so nothing here had a reason to carry a
# marker. Unmarked now means collected but run by no CI job, which the
# census gate correctly refuses.
pytestmark = pytest.mark.unit


@pytest.mark.unit
class TestRepoNameExtraction:
    """Tests for _repo_name and _repo_full_name helpers."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://github.com/org/repo-a.git", "repo-a"),
            ("https://github.com/org/repo-b/", "repo-b"),
            ("https://github.com/org/repo-c", "repo-c"),
            ("https://github.com/org/my.repo.git", "my.repo"),
        ],
    )
    def test_repo_name(self, url: str, expected: str) -> None:
        assert _repo_name(url) == expected

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
        assert "/workspace/repos/repo-a" in script
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
        assert "/workspace/repos/repo-a" in script
        assert "/workspace/repos/repo-b" in script

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
        assert "[ -d /workspace/repos/repo-a ] ||" in script
        assert "[ -d /workspace/repos/repo-b ] ||" in script

    def test_each_repo_initializes_submodules(self) -> None:
        """Every cloned repo gets a recursive submodule init line."""
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/org/repo-a",
                "https://github.com/org/repo-b",
            ],
            repo_tokens={},
        )
        script = secrets.build_setup_script()
        assert "git -C /workspace/repos/repo-a submodule update --init --recursive" in script
        assert "git -C /workspace/repos/repo-b submodule update --init --recursive" in script

    def test_repo_name_with_shell_metacharacters_is_quoted(self) -> None:
        """Paths and URLs are shell-quoted, so a hostile repo name cannot break out.

        RepositoryRef restricts owner/name upstream, but SetupPhaseSecrets accepts raw
        strings; the quoting is enforced here rather than relying on a distant caller.
        """
        hostile = 'https://github.com/org/repo";touch /tmp/pwned;"'
        secrets = SetupPhaseSecrets(repositories=[hostile], repo_tokens={})
        script = secrets.build_setup_script()
        assert "touch /tmp/pwned" not in script.replace(shlex.quote(hostile), "")
        for line in script.splitlines():
            if "git clone" in line or "submodule update" in line:
                assert shlex.split(line.split("|| ")[0]) is not None

    def test_submodule_init_is_non_fatal(self) -> None:
        """A submodule that cannot be fetched must not abort the `set -e` setup script.

        Submodule URLs resolve to repos the installation token may not cover, so
        a hard failure here would break cloning for every repo that has one.
        """
        secrets = SetupPhaseSecrets(
            repositories=["https://github.com/org/repo-a"],
            repo_tokens={},
        )
        script = secrets.build_setup_script()
        submodule_line = next(line for line in script.splitlines() if "submodule update" in line)
        assert submodule_line.rstrip().count("||") == 1
        assert "WARNING" in submodule_line

    def test_submodule_init_runs_even_when_repo_already_cloned(self) -> None:
        """Submodule init sits outside the clone's idempotency guard.

        The clone is skipped when /workspace/repos/<name> already exists (a repeat
        setup phase), but submodules may still be uninitialized from a partial or
        older checkout, so the init must not be guarded away with it.
        """
        secrets = SetupPhaseSecrets(
            repositories=["https://github.com/org/repo-a"],
            repo_tokens={},
        )
        script = secrets.build_setup_script()
        submodule_line = next(line for line in script.splitlines() if "submodule update" in line)
        assert not submodule_line.startswith("[ -d ")

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
class TestRepoNameCollision:
    """Two repositories claiming one /workspace/repos directory (#1223).

    Driven through build_setup_script(), not _clone_destinations directly:
    the script is what provisioning actually consumes, and the defect was a
    clone line silently missing from it.
    """

    def test_same_name_different_orgs_is_refused(self) -> None:
        """(a) Different orgs, same repo name -> refuse, naming both URLs."""
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/acme/api-service",
                "https://github.com/other-org/api-service",
            ],
            repo_tokens={
                "https://github.com/acme/api-service": "tok-acme",
                "https://github.com/other-org/api-service": "tok-other",
            },
        )

        with pytest.raises(RepoNameCollisionError) as exc_info:
            secrets.build_setup_script()

        message = str(exc_info.value)
        # An operator must be able to act on this without reading the source:
        # both offending repos, and the directory they fight over.
        assert "https://github.com/acme/api-service" in message
        assert "https://github.com/other-org/api-service" in message
        assert "/workspace/repos/api-service" in message

    def test_collision_carries_both_urls_as_attributes(self) -> None:
        """The refusal is inspectable, not only printable."""
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/acme/api-service",
                "https://github.com/other-org/api-service",
            ],
        )

        with pytest.raises(RepoNameCollisionError) as exc_info:
            secrets.build_setup_script()

        error = exc_info.value
        assert error.destination == "/workspace/repos/api-service"
        assert error.first_url == "https://github.com/acme/api-service"
        assert error.second_url == "https://github.com/other-org/api-service"

    def test_collision_detected_beyond_the_first_pair(self) -> None:
        """A collision later in the list is caught, not just repos[0] vs [1]."""
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/acme/repo-a",
                "https://github.com/acme/repo-b",
                "https://github.com/other-org/repo-a",
            ],
        )

        with pytest.raises(RepoNameCollisionError) as exc_info:
            secrets.build_setup_script()

        assert exc_info.value.destination == "/workspace/repos/repo-a"
        assert exc_info.value.second_url == "https://github.com/other-org/repo-a"

    def test_different_names_still_clone_both(self) -> None:
        """(b) REGRESSION GUARD: multi-repo is a normal operation here.

        A check that refused legitimate multi-repo executions would be worse
        than the bug it fixes.
        """
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/acme/api-service",
                "https://github.com/other-org/web-service",
            ],
            repo_tokens={
                "https://github.com/acme/api-service": "tok-acme",
                "https://github.com/other-org/web-service": "tok-other",
            },
        )

        script = secrets.build_setup_script()

        assert script.count("git clone") == 2
        assert "[ -d /workspace/repos/api-service ] ||" in script
        assert "[ -d /workspace/repos/web-service ] ||" in script
        assert "https://github.com/acme/api-service" in script
        assert "https://github.com/other-org/web-service" in script

    def test_same_repo_listed_twice_is_deduplicated(self) -> None:
        """(c) Identical URL twice -> de-duplicate, do not refuse.

        Documented decision: the destination is unambiguous and the source is
        the same repository, so there is nothing to get wrong. Re-cloning it
        is exactly the no-op the [ -d ... ] guard exists to make safe, and a
        repos list concatenated from two overlapping sources is a harmless
        configuration that should not fail an execution.
        """
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/acme/api-service",
                "https://github.com/acme/api-service",
            ],
            repo_tokens={"https://github.com/acme/api-service": "tok-acme"},
        )

        script = secrets.build_setup_script()

        # One clone, not two: the repeat is collapsed rather than emitted and
        # then defeated by the guard at runtime.
        assert script.count("git clone") == 1
        assert "[ -d /workspace/repos/api-service ] ||" in script

    def test_spelling_variants_of_one_repo_are_deduplicated(self) -> None:
        """(c, cont.) .git and trailing-slash spellings name the same repo.

        These reach _repo_full_name identically, so they de-duplicate rather
        than colliding - the same normalisation the per-repo credential
        entries already rely on.
        """
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/acme/api-service",
                "https://github.com/acme/api-service.git",
                "https://github.com/acme/api-service/",
            ],
        )

        script = secrets.build_setup_script()

        assert script.count("git clone") == 1

    def test_single_repo_unaffected(self) -> None:
        """(d) One repo -> no new failure path, script unchanged in shape."""
        secrets = SetupPhaseSecrets(
            repositories=["https://github.com/acme/api-service"],
            repo_tokens={"https://github.com/acme/api-service": "tok-acme"},
        )

        script = secrets.build_setup_script()

        assert script.count("git clone") == 1
        assert "[ -d /workspace/repos/api-service ] ||" in script
        assert "git -C /workspace/repos/api-service submodule update --init --recursive" in script

    def test_case_differing_names_do_not_collide(self) -> None:
        """(e) Case-SENSITIVE comparison, matching the target filesystem.

        /workspace is ext4 in the workspace image; API-Service and
        api-service are two distinct directories there (verified by creating
        both). Both clone and both are reachable at the paths a prompt would
        name, so refusing this pair would refuse a configuration that works.

        If the workspace image ever mounted /workspace from a
        case-INSENSITIVE filesystem, these two would collide and
        _clone_destinations would have to case-fold its comparison to stay
        correct. This test pins the current decision so that change is a
        deliberate one.
        """
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/acme/API-Service",
                "https://github.com/other-org/api-service",
            ],
            repo_tokens={
                "https://github.com/acme/API-Service": "tok-acme",
                "https://github.com/other-org/api-service": "tok-other",
            },
        )

        script = secrets.build_setup_script()

        assert script.count("git clone") == 2
        assert "[ -d /workspace/repos/API-Service ] ||" in script
        assert "[ -d /workspace/repos/api-service ] ||" in script

    def test_clone_order_follows_configured_order(self) -> None:
        """De-duplication preserves configured order, first spelling wins."""
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/acme/repo-b",
                "https://github.com/acme/repo-a",
                "https://github.com/acme/repo-b",
            ],
        )

        script = secrets.build_setup_script()

        assert script.count("git clone") == 2
        assert script.index("/workspace/repos/repo-b") < script.index("/workspace/repos/repo-a")

    def test_collision_is_not_checked_when_repos_are_not_cloned(self) -> None:
        """clone_repos=False creates no directories, so there is no collision.

        Such a phase is credentialed but never checked out (#1187), and
        credentials are keyed by owner/repo, which does not collide. Refusing
        here would reject a configuration that cannot go wrong.
        """
        secrets = SetupPhaseSecrets(
            repositories=[
                "https://github.com/acme/api-service",
                "https://github.com/other-org/api-service",
            ],
            repo_tokens={
                "https://github.com/acme/api-service": "tok-acme",
                "https://github.com/other-org/api-service": "tok-other",
            },
            clone_repos=False,
        )

        script = secrets.build_setup_script()

        assert "git clone" not in script
        assert "x-access-token:tok-acme@github.com/acme/api-service" in script
        assert "x-access-token:tok-other@github.com/other-org/api-service" in script


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
