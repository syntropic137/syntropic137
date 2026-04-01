"""Tests for workflow export CLI command — syn workflow export."""

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
    client.__enter__ = lambda _self: client
    client.__exit__ = MagicMock(return_value=False)
    return client


_EXPORT_RESPONSE_PACKAGE: dict = {
    "format": "package",
    "workflow_id": "deep-research-v1",
    "workflow_name": "Deep Research",
    "files": {
        "workflow.yaml": (
            "id: deep-research-v1\n"
            "name: Deep Research\n"
            "type: research\n"
            "classification: standard\n"
            "\n"
            "phases:\n"
            "  - id: discovery\n"
            "    name: Discovery\n"
            "    order: 1\n"
            "    prompt_file: phases/discovery.md\n"
        ),
        "phases/discovery.md": (
            "---\n"
            "model: sonnet\n"
            'argument-hint: "[topic]"\n'
            "allowed-tools: Read,Grep,Bash\n"
            "---\n\n"
            "Research the topic: $ARGUMENTS\n"
        ),
        "README.md": "# Deep Research\n\nA research workflow.\n",
    },
}

_EXPORT_RESPONSE_PLUGIN: dict = {
    "format": "plugin",
    "workflow_id": "deep-research-v1",
    "workflow_name": "Deep Research",
    "files": {
        "syntropic137.yaml": 'manifest_version: 1\nname: deep-research\nversion: "0.1.0"\n',
        "README.md": "# Deep Research\n",
        "commands/syn-deep-research.md": "---\nmodel: sonnet\n---\n\nRun workflow.\n",
        "workflows/deep-research/workflow.yaml": "id: deep-research-v1\n",
        "workflows/deep-research/phases/discovery.md": "---\nmodel: sonnet\n---\n\nPrompt.\n",
    },
}


# ---------------------------------------------------------------------------
# syn workflow export
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExportWorkflow:
    def test_export_package_writes_files(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "export"
        resp = _mock_response(200, _EXPORT_RESPONSE_PACKAGE)
        client = _mock_client(resp)

        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(
                app,
                ["workflow", "export", "deep-research-v1", "--output", str(out_dir)],
            )

        assert result.exit_code == 0, result.stdout
        assert (out_dir / "workflow.yaml").exists()
        assert (out_dir / "phases" / "discovery.md").exists()
        assert (out_dir / "README.md").exists()

    def test_export_plugin_writes_files(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "plugin"
        resp = _mock_response(200, _EXPORT_RESPONSE_PLUGIN)
        client = _mock_client(resp)

        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(
                app,
                [
                    "workflow", "export", "deep-research-v1",
                    "--format", "plugin",
                    "--output", str(out_dir),
                ],
            )

        assert result.exit_code == 0, result.stdout
        assert (out_dir / "syntropic137.yaml").exists()
        assert (out_dir / "commands" / "syn-deep-research.md").exists()
        assert (out_dir / "workflows" / "deep-research" / "workflow.yaml").exists()

    def test_export_non_empty_dir_fails(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "notempty"
        out_dir.mkdir()
        (out_dir / "existing.txt").write_text("x")

        resp = _mock_response(200, _EXPORT_RESPONSE_PACKAGE)
        client = _mock_client(resp)

        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(
                app,
                ["workflow", "export", "deep-research-v1", "--output", str(out_dir)],
            )

        assert result.exit_code == 1
        assert "not empty" in result.stdout

    def test_export_invalid_format_fails(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "bad"
        result = runner.invoke(
            app,
            [
                "workflow", "export", "deep-research-v1",
                "--format", "zip",
                "--output", str(out_dir),
            ],
        )
        assert result.exit_code == 1
        assert "Invalid format" in result.stdout

    def test_export_creates_output_dir(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "new" / "nested" / "dir"
        resp = _mock_response(200, _EXPORT_RESPONSE_PACKAGE)
        client = _mock_client(resp)

        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(
                app,
                ["workflow", "export", "deep-research-v1", "--output", str(out_dir)],
            )

        assert result.exit_code == 0, result.stdout
        assert out_dir.exists()
        assert (out_dir / "workflow.yaml").exists()

    def test_export_file_content_preserved(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "content"
        resp = _mock_response(200, _EXPORT_RESPONSE_PACKAGE)
        client = _mock_client(resp)

        with patch(_HELPERS_CLIENT, return_value=client):
            runner.invoke(
                app,
                ["workflow", "export", "deep-research-v1", "--output", str(out_dir)],
            )

        md_content = (out_dir / "phases" / "discovery.md").read_text()
        assert "model: sonnet" in md_content
        assert "Research the topic: $ARGUMENTS" in md_content

    def test_export_shows_summary(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "summary"
        resp = _mock_response(200, _EXPORT_RESPONSE_PACKAGE)
        client = _mock_client(resp)

        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(
                app,
                ["workflow", "export", "deep-research-v1", "--output", str(out_dir)],
            )

        assert "Export Complete" in result.stdout
        assert "Deep Research" in result.stdout

    def test_export_api_404(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "notfound"
        resp = _mock_response(404, {"detail": "Workflow not-found not found"})
        client = _mock_client(resp)

        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(
                app,
                ["workflow", "export", "not-found", "--output", str(out_dir)],
            )

        assert result.exit_code == 1
