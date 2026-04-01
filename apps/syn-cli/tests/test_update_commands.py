"""Tests for workflow update and uninstall CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from syn_cli.commands._package_models import (
    InstallationRecord,
    InstalledRegistry,
    InstalledWorkflowRef,
)
from syn_cli.main import app

runner = CliRunner()

_LOAD_INSTALLED = "syn_cli.commands.workflow._update.load_installed"
_SAVE_INSTALLED = "syn_cli.commands.workflow._update.save_installed"
_HELPERS_CLIENT = "syn_cli.commands._api_helpers.get_client"


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def _mock_client(*responses: MagicMock) -> MagicMock:
    client = MagicMock()
    all_responses = list(responses)
    call_idx = {"i": 0}

    def _next_response(*_args: object, **_kwargs: object) -> MagicMock:
        idx = call_idx["i"]
        call_idx["i"] += 1
        return all_responses[idx] if idx < len(all_responses) else _mock_response()

    client.get.side_effect = _next_response
    client.post.side_effect = _next_response
    client.delete.side_effect = _next_response
    client.__enter__ = lambda _self: client
    client.__exit__ = MagicMock(return_value=False)
    return client


def _make_registry(
    name: str = "test-plugin",
    marketplace_source: str | None = None,
    git_sha: str | None = None,
) -> InstalledRegistry:
    return InstalledRegistry(
        installations=[
            InstallationRecord(
                package_name=name,
                package_version="1.0.0",
                source=name if marketplace_source else "./test",
                source_ref="main",
                installed_at="2026-01-01T00:00:00+00:00",
                format="multi",
                workflows=[
                    InstalledWorkflowRef(id="wf-1", name="Workflow 1"),
                    InstalledWorkflowRef(id="wf-2", name="Workflow 2"),
                ],
                marketplace_source=marketplace_source,
                git_sha=git_sha,
            )
        ]
    )


class TestUninstallWorkflow:
    @patch(_SAVE_INSTALLED)
    @patch(_LOAD_INSTALLED)
    def test_uninstall_with_api_delete(
        self,
        mock_load: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        mock_load.return_value = _make_registry()
        client = _mock_client(
            _mock_response(200),  # DELETE wf-1
            _mock_response(200),  # DELETE wf-2
        )

        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["workflow", "uninstall", "test-plugin"])

        assert result.exit_code == 0
        assert "Uninstalled" in result.stdout
        mock_save.assert_called_once()

    @patch(_SAVE_INSTALLED)
    @patch(_LOAD_INSTALLED)
    def test_uninstall_keep_workflows(
        self,
        mock_load: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        mock_load.return_value = _make_registry()

        result = runner.invoke(
            app, ["workflow", "uninstall", "test-plugin", "--keep-workflows"]
        )

        assert result.exit_code == 0
        assert "Uninstalled" in result.stdout
        mock_save.assert_called_once()

    @patch(_LOAD_INSTALLED)
    def test_uninstall_not_found(self, mock_load: MagicMock) -> None:
        mock_load.return_value = InstalledRegistry()

        result = runner.invoke(app, ["workflow", "uninstall", "nonexistent"])
        assert result.exit_code == 1
        assert "not installed" in result.stdout


class TestUpdateWorkflow:
    @patch(_LOAD_INSTALLED)
    def test_update_not_installed(self, mock_load: MagicMock) -> None:
        mock_load.return_value = InstalledRegistry()

        result = runner.invoke(app, ["workflow", "update", "nonexistent"])
        assert result.exit_code == 1
        assert "not installed" in result.stdout

    @patch("syn_cli.commands.workflow._update._try_marketplace_resolution")
    @patch("syn_cli.commands._marketplace_client.get_git_head_sha")
    @patch("syn_cli.commands._marketplace_client.resolve_plugin_by_name")
    @patch(_LOAD_INSTALLED)
    def test_update_already_current(
        self,
        mock_load: MagicMock,
        mock_resolve: MagicMock,
        mock_sha: MagicMock,
        mock_try_mkt: MagicMock,
    ) -> None:
        mock_load.return_value = _make_registry(
            marketplace_source="official",
            git_sha="abc123",
        )
        from syn_cli.commands._marketplace_models import RegistryEntry

        mock_resolve.return_value = (
            "official",
            RegistryEntry(repo="org/repo", added_at="2026-01-01T00:00:00+00:00"),
            MagicMock(),
        )
        mock_sha.return_value = "abc123"  # Same SHA = no update

        result = runner.invoke(app, ["workflow", "update", "test-plugin"])
        assert result.exit_code == 0
        assert "already up to date" in result.stdout
