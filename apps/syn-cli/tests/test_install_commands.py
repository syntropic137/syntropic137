"""Tests for workflow install CLI commands — install, installed, init."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest
from typer.testing import CliRunner

from syn_cli.main import app

runner = CliRunner()

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
    client.__enter__ = lambda _self: client
    client.__exit__ = MagicMock(return_value=False)
    return client


def _write_single_package(pkg_dir: Path) -> None:
    """Create a minimal single-workflow package for testing."""
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "workflow.yaml").write_text(
        """\
id: test-install-v1
name: Test Install Workflow
type: research
classification: standard
phases:
  - id: phase-1
    name: Phase One
    order: 1
    prompt_template: "Do the thing"
"""
    )


# ---------------------------------------------------------------------------
# syn workflow install
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallWorkflow:
    def test_install_local_single(self, tmp_path: Path) -> None:
        _write_single_package(tmp_path / "pkg")
        created_resp = _mock_response(
            201,
            {
                "id": "wf-abc123",
                "name": "Test Install Workflow",
                "workflow_type": "research",
                "status": "created",
            },
        )
        client = _mock_client(created_resp)
        with (
            patch(_HELPERS_CLIENT, return_value=client),
            patch("syn_cli.commands._package_resolver.record_installation"),
        ):
            result = runner.invoke(app, ["workflow", "install", str(tmp_path / "pkg")])
        assert result.exit_code == 0
        assert "Installed 1 workflow" in result.stdout

    def test_install_dry_run(self, tmp_path: Path) -> None:
        _write_single_package(tmp_path / "pkg")
        result = runner.invoke(app, ["workflow", "install", str(tmp_path / "pkg"), "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.stdout

    def test_install_nonexistent_path(self) -> None:
        result = runner.invoke(app, ["workflow", "install", "/nonexistent/path"])
        assert result.exit_code == 1

    def test_install_empty_dir(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["workflow", "install", str(tmp_path)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# syn workflow installed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListInstalled:
    def test_installed_empty(self, tmp_path: Path) -> None:
        with patch(
            "syn_cli.commands._package_resolver._INSTALLED_PATH",
            tmp_path / "nonexistent" / "installed.json",
        ):
            result = runner.invoke(app, ["workflow", "installed"])
        assert result.exit_code == 0
        assert "No packages installed" in result.stdout

    def test_installed_with_records(self, tmp_path: Path) -> None:
        installed_file = tmp_path / "installed.json"
        installed_file.write_text(
            '{"version": 1, "installations": [{"package_name": "test-pkg", '
            '"package_version": "1.0.0", "source": "./test", "source_ref": "main", '
            '"installed_at": "2026-03-30T00:00:00Z", "format": "single", '
            '"workflows": [{"id": "wf-1", "name": "Test"}]}]}'
        )
        with patch("syn_cli.commands._package_resolver._INSTALLED_PATH", installed_file):
            result = runner.invoke(app, ["workflow", "installed"])
        assert result.exit_code == 0
        assert "test-pkg" in result.stdout


# ---------------------------------------------------------------------------
# syn workflow init
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitPackage:
    def test_init_single(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "new-workflow"
        result = runner.invoke(
            app,
            ["workflow", "init", str(pkg_dir), "--name", "My Workflow", "--phases", "2"],
        )
        assert result.exit_code == 0
        assert "Scaffolded" in result.stdout
        assert (pkg_dir / "workflow.yaml").exists()
        assert (pkg_dir / "phases").is_dir()

    def test_init_multi(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "new-plugin"
        result = runner.invoke(
            app,
            ["workflow", "init", str(pkg_dir), "--name", "My Plugin", "--multi"],
        )
        assert result.exit_code == 0
        assert "multi-workflow plugin" in result.stdout
        assert (pkg_dir / "syntropic137.yaml").exists()
        assert (pkg_dir / "phase-library").is_dir()

    def test_init_nonempty_dir_fails(self, tmp_path: Path) -> None:
        (tmp_path / "existing-file.txt").write_text("hello")
        result = runner.invoke(app, ["workflow", "init", str(tmp_path)])
        assert result.exit_code == 1
        assert "not empty" in result.stdout


# ---------------------------------------------------------------------------
# syn workflow validate (directory)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateDirectory:
    def test_validate_single_package(self, tmp_path: Path) -> None:
        _write_single_package(tmp_path / "pkg")
        result = runner.invoke(app, ["workflow", "validate", str(tmp_path / "pkg")])
        assert result.exit_code == 0
        assert "Valid single package" in result.stdout

    def test_validate_empty_dir_fails(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["workflow", "validate", str(tmp_path)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Help text includes new commands
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHelpIncludes:
    def test_workflow_help_shows_new_commands(self) -> None:
        result = runner.invoke(app, ["workflow", "--help"])
        assert result.exit_code == 0
        for cmd in ("install", "installed", "init"):
            assert cmd in result.stdout
