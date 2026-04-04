"""Tests for image version manifest extraction from workspace containers.

Verifies _read_image_manifest() handles:
- Valid version.json → ImageManifest
- Missing version.json (old image) → None
- Malformed JSON → None with no crash
- No provider (memory backend) → None
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from syn_adapters.workspace_backends.service.workspace_lifecycle import (
    _read_image_manifest,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ImageManifest,
    IsolationHandle,
)

SAMPLE_VERSION_JSON: dict[str, Any] = {
    "provider": "claude-cli",
    "provider_version": "1.1.0",
    "components": {
        "claude_cli": "2.1.76",
        "rtk": "0.34.3",
        "node": "22",
        "python": "3.12",
    },
    "build_commit": "e63b4458332a",
    "built_at": "2026-04-04T16:58:05.907070+00:00",
    "manifest_digest": "d55e27a49de81850",
}

HANDLE = IsolationHandle(
    isolation_id="container-abc123",
    isolation_type="docker",
)


def _mock_service(
    exec_exit_code: int = 0,
    exec_output: bytes = b"",
    *,
    has_provider: bool = True,
    has_container: bool = True,
) -> MagicMock:
    """Build a mock WorkspaceService with configurable container exec behavior."""
    service = MagicMock()

    if not has_provider:
        service._isolation._provider = None
        del service._isolation._provider
        return service

    container = MagicMock()
    container.exec_run.return_value = (exec_exit_code, exec_output)

    if has_container:
        service._isolation._provider._active_workspaces = {
            HANDLE.isolation_id: container,
        }
    else:
        service._isolation._provider._active_workspaces = {}

    return service


@pytest.mark.unit
class TestReadImageManifest:
    """Tests for _read_image_manifest."""

    @pytest.mark.asyncio
    async def test_valid_version_json(self) -> None:
        """Valid version.json should return ImageManifest."""
        service = _mock_service(
            exec_exit_code=0,
            exec_output=json.dumps(SAMPLE_VERSION_JSON).encode(),
        )

        result = await _read_image_manifest(service, HANDLE)

        assert result is not None
        assert isinstance(result, ImageManifest)
        assert result.provider == "claude-cli"
        assert result.provider_version == "1.1.0"
        assert result.components["claude_cli"] == "2.1.76"
        assert result.components["rtk"] == "0.34.3"
        assert result.build_commit == "e63b4458332a"

    @pytest.mark.asyncio
    async def test_missing_version_json(self) -> None:
        """Old image without version.json → None (no crash)."""
        service = _mock_service(exec_exit_code=1, exec_output=b"cat: No such file")

        result = await _read_image_manifest(service, HANDLE)

        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_json(self) -> None:
        """Malformed JSON → None (no crash)."""
        service = _mock_service(exec_exit_code=0, exec_output=b"not json {{{")

        result = await _read_image_manifest(service, HANDLE)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_provider(self) -> None:
        """Memory backend without _provider → None."""
        service = _mock_service(has_provider=False)

        result = await _read_image_manifest(service, HANDLE)

        assert result is None

    @pytest.mark.asyncio
    async def test_container_not_found(self) -> None:
        """Container not in _active_workspaces → None."""
        service = _mock_service(has_container=False)

        result = await _read_image_manifest(service, HANDLE)

        assert result is None

    @pytest.mark.asyncio
    async def test_partial_version_json(self) -> None:
        """version.json with missing optional fields → ImageManifest with defaults."""
        partial = {"provider": "claude-cli", "provider_version": "1.0.0", "components": {}}
        service = _mock_service(
            exec_exit_code=0,
            exec_output=json.dumps(partial).encode(),
        )

        result = await _read_image_manifest(service, HANDLE)

        assert result is not None
        assert result.provider == "claude-cli"
        assert result.build_commit == ""
        assert result.components == {}
