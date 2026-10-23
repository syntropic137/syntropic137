"""The image manifest, and artifacts, read through the provider's file transfer (#1913).

Driven through production wiring: `WorkspaceService.create` selects the
backend, the `AgenticIsolationAdapter` routes the read, and the real
`E2BWorkspaceProvider` satisfies `SupportsFileTransfer` over an in-memory E2B
account (`SandboxDouble`). The Docker cases use a provider fake at the same
Protocol boundary, because the bind-mount read is the thing that must not run.

Replaces `test_version_manifest_extraction.py`, which seeded a private
`_active_workspaces` attribute that no pinned provider has, so it passed while
production returned None on every backend.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from syn_adapters.workspace_backends.agentic import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic import adapter as adapter_module
from syn_adapters.workspace_backends.backend_kit import BackendKit
from syn_adapters.workspace_backends.e2b import e2b_conformance as suite
from syn_adapters.workspace_backends.e2b.test_e2b_backend import SandboxDouble, _enabled
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_adapters.workspace_backends.service.workspace_lifecycle import (
    _read_image_manifest,
    create_workspace_aggregate,
    provision_workspace,
)
from syn_domain.contexts.orchestration import ImageManifestContent, ImageManifestState
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

MANIFEST_PATH = "/opt/agentic/version.json"
MANIFEST = {
    "provider": "claude-cli",
    "provider_version": "1.1.0",
    "components": {"claude_cli": "2.1.76", "rtk": "0.34.3"},
    "build_commit": "e63b4458332a",
    "built_at": "2026-10-01T00:00:00+00:00",
    "manifest_digest": "d55e27a49de81850",
}


class _SeededSandboxes(SandboxDouble):
    """An E2B account whose every new sandbox already holds ``files``, as an image would."""

    def __init__(self, files: dict[str, bytes]) -> None:
        super().__init__()
        self.files = files

    async def create(self, **kwargs: object) -> str:
        sandbox_id = await super().create(**kwargs)  # type: ignore[arg-type]
        self.sandboxes[sandbox_id][1].update(self.files)
        return sandbox_id


class _BrokenReads(_SeededSandboxes):
    async def read_bytes(self, sandbox_id: str, path: str, *, user: str) -> bytes:
        raise RuntimeError(f"sandbox {sandbox_id} stopped answering")


def _e2b(monkeypatch: pytest.MonkeyPatch, double: SandboxDouble) -> WorkspaceService:
    return WorkspaceService.create(
        backend=WorkspaceBackend.E2B, e2b=_enabled(monkeypatch), e2b_client=double
    )


@pytest.fixture
def no_host_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bind-mount read, made to fail loudly if anything reaches it."""

    async def host_read(*_: object, **__: object) -> list[tuple[str, bytes]]:
        raise AssertionError("read a workspace file from a host path")

    monkeypatch.setattr(adapter_module, "copy_files_from_workspace", host_read)


async def test_provisioning_records_the_manifest_read_through_the_provider(
    monkeypatch: pytest.MonkeyPatch, no_host_reads: None
) -> None:
    service = _e2b(monkeypatch, _SeededSandboxes({MANIFEST_PATH: json.dumps(MANIFEST).encode()}))
    config = suite.isolation_config(service._config.image)
    aggregate = create_workspace_aggregate(
        workspace_id=config.workspace_id,
        execution_id=config.execution_id,
        workflow_id=None,
        phase_id=None,
        backend=config.backend,
        capabilities=config.capabilities,
        image=config.image,
    )

    _, _, reading = await provision_workspace(
        service, config, aggregate, config.workspace_id, with_sidecar=False
    )

    assert reading.state is ImageManifestState.READ
    assert reading.manifest == ImageManifestContent(**MANIFEST)
    assert aggregate.image_manifest is not None
    assert aggregate.image_manifest.build_commit == "e63b4458332a"


async def test_an_image_with_no_manifest_is_recorded_absent(
    monkeypatch: pytest.MonkeyPatch, no_host_reads: None
) -> None:
    """Every image today (AgentParadise/agentic-workspace#93)."""
    service = _e2b(monkeypatch, _SeededSandboxes({}))
    handle = await service._isolation.create(suite.isolation_config(service._config.image))

    reading = await _read_image_manifest(service, handle)

    assert reading.state is ImageManifestState.ABSENT
    assert reading.manifest is None


async def test_a_failed_transfer_is_recorded_unreadable_never_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _e2b(monkeypatch, _BrokenReads({MANIFEST_PATH: b"{}"}))
    handle = await service._isolation.create(suite.isolation_config(service._config.image))

    reading = await _read_image_manifest(service, handle)

    assert reading.state is ImageManifestState.UNREADABLE
    assert reading.detail is not None
    assert "stopped answering" in reading.detail


async def test_remote_artifacts_come_back_through_the_provider_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch, no_host_reads: None
) -> None:
    blob = bytes(range(256))
    service = _e2b(monkeypatch, _SeededSandboxes({"/workspace/artifacts/output/a.bin": blob}))
    handle = await service._isolation.create(suite.isolation_config(service._config.image))
    assert not handle.host_workspace_path

    got = await service._isolation.copy_from(handle, ["artifacts/output/*"])

    assert got == [("artifacts/output/a.bin", blob)]


class _TransferOnly:
    """A provider fake at the `SupportsFileTransfer` boundary: it records each read."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.reads: list[str] = []

    async def read_files(
        self, workspace: object, patterns: Sequence[str], *, base_path: str
    ) -> list[tuple[str, bytes]]:
        self.reads.append(base_path)
        return [
            (path.removeprefix(base_path + "/"), content)
            for path, content in self.files.items()
            if path.startswith(base_path + "/")
        ]


def _docker_with(provider: _TransferOnly) -> tuple[AgenticIsolationAdapter, IsolationHandle]:
    adapter = AgenticIsolationAdapter(kit=BackendKit(), provider=provider)  # type: ignore[arg-type]
    handle = IsolationHandle(isolation_id="ws-docker", isolation_type="docker")
    adapter._workspaces[handle.isolation_id] = object()  # type: ignore[assignment]  # only looked up
    return adapter, handle


async def test_docker_reads_the_manifest_through_the_provider_not_its_mount(
    no_host_reads: None,
) -> None:
    """The mount is /workspace only, and ignores `base_path`: it cannot hold /opt/agentic."""
    provider = _TransferOnly({MANIFEST_PATH: json.dumps(MANIFEST).encode()})
    adapter, handle = _docker_with(provider)

    got = await adapter.copy_from(handle, ["version.json"], "/opt/agentic")

    assert got == [("version.json", json.dumps(MANIFEST).encode())]
    assert provider.reads == ["/opt/agentic"]
