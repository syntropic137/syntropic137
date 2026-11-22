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
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from agentic_isolation.config import WorkspaceConfig
from agentic_isolation.providers.base import Workspace
from agentic_isolation.providers.file_transfer import (
    DEFAULT_READ_LIMITS,
    ReadFilesResult,
    ReadLimits,
)

from syn_adapters.workspace_backends.agentic import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic import adapter as adapter_module
from syn_adapters.workspace_backends.backend_kit import BackendKit
from syn_adapters.workspace_backends.e2b import e2b_conformance as suite
from syn_adapters.workspace_backends.e2b.test_e2b_backend import (
    SandboxDouble,
    _Command,
    _enabled,
)
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_adapters.workspace_backends.service.workspace_lifecycle import (
    _read_image_manifest,
    create_workspace_aggregate,
    provision_workspace,
)
from syn_domain.contexts.orchestration import (
    ImageManifestContent,
    ImageManifestReading,
    ImageManifestState,
)
from syn_domain.contexts.orchestration._shared.file_transfer import (
    FileRefusal,
    FilesRefusedError,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.test_1913_image_manifest_reading import (
    _replayed,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agentic_isolation import AgenticWorkspace
    from agentic_isolation.providers.base import WorkspaceProvider
    from agentic_isolation.providers.capabilities import TransferRoot

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
    """The sandbox lists the root, then stops answering when the files are read.

    The provider reads over the command stream (`start`), not the files API,
    so that is where the failure has to be.
    """

    async def start(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None,
        env: Mapping[str, str],
        timeout: float | None,
        user: str,
        stdin: bytes | None = None,
    ) -> _Command:
        if "xargs -0" in command:
            raise RuntimeError(f"sandbox {sandbox_id} stopped answering")
        return await super().start(
            sandbox_id, command, cwd=cwd, env=env, timeout=timeout, user=user, stdin=stdin
        )


class _LinkedManifest(_SeededSandboxes):
    """The image's version.json is a symlink out of /opt/agentic."""

    @staticmethod
    def _listing(files: Mapping[str, bytes], root: str) -> bytes:
        return SandboxDouble._listing(files, root) + b"l 1 11 1\0version.json\0/etc/passwd\0"


class _DeepAndLinkedManifest(_SeededSandboxes):
    """version.json is a link out of /opt/agentic, and a directory past the depth limit."""

    @staticmethod
    def _listing(files: Mapping[str, bytes], root: str) -> bytes:
        too_deep = adapter_module.collection_read_limits().max_depth + 1
        return _LinkedManifest._listing(files, root) + f"d 1 0 {too_deep}\0a-deep\0\0".encode()


class _LinkedArtifact(_SeededSandboxes):
    """Beside a real artifact the agent left a symlink, then a hard link."""

    @staticmethod
    def _listing(files: Mapping[str, bytes], root: str) -> bytes:
        return SandboxDouble._listing(files, root) + (
            b"l 1 11 3\0artifacts/output/b.lnk\0/etc/passwd\0f 2 4 3\0artifacts/output/c.txt\0\0"
        )


def _e2b(monkeypatch: pytest.MonkeyPatch, double: SandboxDouble) -> WorkspaceService:
    return WorkspaceService.create(
        backend=WorkspaceBackend.E2B, e2b=_enabled(monkeypatch), e2b_client=double
    )


async def test_provisioning_records_the_manifest_read_through_the_provider(
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blob = bytes(range(256))
    service = _e2b(monkeypatch, _SeededSandboxes({"/workspace/artifacts/output/a.bin": blob}))
    handle = await service._isolation.create(suite.isolation_config(service._config.image))
    assert not handle.host_workspace_path

    got = await service._isolation.copy_from(handle, ["artifacts/output/*"])

    assert got == [("artifacts/output/a.bin", blob)]


class _TransferOnly:
    """A provider at the `SupportsFileTransfer` boundary of the pinned contract: it records each read."""

    name = "docker"

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.reads: list[tuple[str, ReadLimits]] = []

    async def read_files(
        self,
        workspace: Workspace,
        patterns: Sequence[str],
        *,
        base_path: TransferRoot,
        limits: ReadLimits = DEFAULT_READ_LIMITS,
    ) -> ReadFilesResult:
        self.reads.append((base_path, limits))
        files = tuple(
            (path.removeprefix(base_path + "/"), content)
            for path, content in self.files.items()
            if path.startswith(base_path + "/")
        )
        return ReadFilesResult(files=files, refused=())


def _docker_with(provider: _TransferOnly) -> tuple[AgenticIsolationAdapter, IsolationHandle]:
    """The Docker kit (no remote flag), so the routing decision is Docker's own."""
    adapter = AgenticIsolationAdapter(
        kit=BackendKit(), provider=lambda _: cast("WorkspaceProvider", provider)
    )
    handle = IsolationHandle(isolation_id="ws-docker", isolation_type="docker")
    adapter._workspaces[handle.isolation_id] = cast(
        "AgenticWorkspace",
        Workspace(
            id="ws-docker", provider="docker", path=Path("/workspace"), config=WorkspaceConfig()
        ),
    )
    return adapter, handle


async def test_docker_reads_the_manifest_through_the_provider_not_its_mount() -> None:
    """The mount is /workspace only, and ignores `base_path`: it cannot hold /opt/agentic."""
    provider = _TransferOnly({MANIFEST_PATH: json.dumps(MANIFEST).encode()})
    adapter, handle = _docker_with(provider)

    got = await adapter.copy_from(handle, ["version.json"], "/opt/agentic")

    assert got == [("version.json", json.dumps(MANIFEST).encode())]
    assert [root for root, _ in provider.reads] == ["/opt/agentic"]


async def test_docker_artifacts_come_back_through_the_bounded_provider_read() -> None:
    """B2 is closed: Docker's /workspace is read by the provider, within chosen budgets."""
    blob = bytes(range(256))
    provider = _TransferOnly({"/workspace/artifacts/output/a.bin": blob})
    adapter, handle = _docker_with(provider)

    got = await adapter.copy_from(handle, ["artifacts/output/*"])

    assert got == [("artifacts/output/a.bin", blob)]
    assert provider.reads == [("/workspace", adapter_module.collection_read_limits())]
    assert provider.reads[0][1] != DEFAULT_READ_LIMITS


async def test_a_refused_manifest_is_recorded_unreadable_with_its_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _e2b(monkeypatch, _LinkedManifest({}))
    handle = await service._isolation.create(suite.isolation_config(service._config.image))

    reading = await _read_image_manifest(service, handle)

    assert reading == ImageManifestReading.refused(
        (FileRefusal(path="version.json", reason="escaping_symlink"),)
    )
    assert reading.state is ImageManifestState.UNREADABLE
    assert reading.manifest is None


async def test_every_manifest_refusal_is_recorded_and_survives_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The walk stopping AND the manifest refused: both kept, not the first (#1913)."""
    service = _e2b(monkeypatch, _DeepAndLinkedManifest({}))
    handle = await service._isolation.create(suite.isolation_config(service._config.image))

    reading = await _read_image_manifest(service, handle)

    both = (
        FileRefusal(path="version.json", reason="escaping_symlink"),
        FileRefusal(path="a-deep", reason="depth_exceeded"),
    )
    assert reading.state is ImageManifestState.UNREADABLE
    assert sorted(reading.refusals, key=lambda r: r.path) == sorted(both, key=lambda r: r.path)
    assert reading.detail is not None
    assert "version.json (escaping_symlink)" in reading.detail
    assert "a-deep (depth_exceeded)" in reading.detail
    assert _replayed(reading).image_manifest_for("build") == reading


async def test_refused_artifacts_are_named_and_the_read_ones_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed result: nothing refused is dropped, nothing read is lost, nothing is empty."""
    blob = bytes(range(256))
    service = _e2b(monkeypatch, _LinkedArtifact({"/workspace/artifacts/output/a.bin": blob}))
    handle = await service._isolation.create(suite.isolation_config(service._config.image))

    with pytest.raises(FilesRefusedError) as raised:
        await service._isolation.copy_from(handle, ["artifacts/output/*"])

    assert raised.value.refused == (
        FileRefusal(path="artifacts/output/b.lnk", reason="escaping_symlink"),
        FileRefusal(path="artifacts/output/c.txt", reason="hard_link"),
    )
    assert raised.value.files == (("artifacts/output/a.bin", blob),)
    assert raised.value.complete


def test_no_type_ignore_hides_the_provider_read_contract() -> None:
    """PC-239: an ignore on the read_files call hid its return type changing under us.

    pyright checks the call only while nothing suppresses it, so the source
    must carry no suppression on any line of the call into the AW port.
    """
    import ast
    import inspect

    source = inspect.getsource(adapter_module)
    lines = source.splitlines()
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_files"
    ]
    assert calls, "the adapter no longer calls read_files"
    for call in calls:
        start = call.lineno - 1
        end = call.end_lineno or call.lineno
        suppressed = [line for line in lines[start:end] if "type: ignore" in line]
        assert not suppressed, suppressed
