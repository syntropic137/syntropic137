"""E2B backend, shipped dark (#1915): config, selection, wiring and conformance.

Runs in CI with no E2B account: the real ``E2BWorkspaceProvider`` from
agentic-workspace is driven over ``SandboxDouble``, an in-memory
``E2BSandboxClient``. That proves Syn137's wiring and the suite, not E2B;
``live_e2b_suite.py`` runs the same suite against real E2B.
"""

from __future__ import annotations

import base64
import os
import posixpath
import shlex
from typing import TYPE_CHECKING

import pytest
from agentic_isolation import E2BWorkspaceProvider
from agentic_isolation.providers import e2b as e2b_provider
from agentic_isolation.providers.base import SupportsOperations
from agentic_isolation.providers.e2b_client import CommandExit, SandboxListing
from pydantic import ValidationError

from syn_adapters.workspace_backends.agentic import AgenticIsolationAdapter
from syn_adapters.workspace_backends.backend_kit import BackendKit, WorkspaceCapacityError
from syn_adapters.workspace_backends.e2b import e2b_conformance as suite
from syn_adapters.workspace_backends.errors import (
    WorkspaceProvisionError,
    WorkspaceTeardownError,
)
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_shared.settings.e2b import E2BSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

pytestmark = pytest.mark.unit

_KEY = "e2b_test_key_not_real"
_TEMPLATE = "syn-e2b-conformance-template"


class _Command:
    def __init__(self, pid: int, text: str, code: int) -> None:
        self._pid, self._text, self._code = pid, text, code

    @property
    def pid(self) -> int:
        return self._pid

    async def output(self) -> AsyncIterator[str]:
        if self._text:
            yield self._text

    async def wait(self) -> CommandExit:
        return CommandExit(end="exited", exit_code=self._code)

    async def kill(self) -> bool:
        return False


class SandboxDouble:
    """An in-memory E2B account. Commands are answered from a script.

    The provider wraps every command as ``sh -c 'exec "$@" 2>&1' sh sh -c CMD``,
    so the script is keyed by the innermost ``CMD``; unknown commands succeed
    silently, which is what the provider's own probes (writable roots,
    TMPDIR) need. ``read_files`` walks and reads with GNU-only shell scripts,
    so those two are answered from the stored files in the records the
    scripts would print (agentic_isolation.providers.file_transfer).
    """

    def __init__(self, *, kill_is_noop: bool = False) -> None:
        if "PYTEST_CURRENT_TEST" not in os.environ:
            raise RuntimeError("SandboxDouble is a test double; it refuses to run outside pytest")
        self.kill_is_noop = kill_is_noop
        self.sandboxes: dict[str, tuple[dict[str, str], dict[str, bytes]]] = {}
        self.created_from: list[str] = []
        self.lifetimes: list[int] = []
        self._pids = 0
        self.script = {
            shlex.join(suite.MERGED_COMMAND): (suite.MERGED_OUTPUT, 3),
        }

    async def create(
        self, *, template: str, metadata: Mapping[str, str], lifetime_seconds: int
    ) -> str:
        sandbox_id = f"sbx-{len(self.created_from) + 1}"
        self.created_from.append(template)
        self.lifetimes.append(lifetime_seconds)
        self.sandboxes[sandbox_id] = (dict(metadata), {})
        return sandbox_id

    async def list(self, metadata: Mapping[str, str]) -> list[SandboxListing]:
        return [
            SandboxListing(sid, labels)
            for sid, (labels, _) in self.sandboxes.items()
            if all(labels.get(k) == v for k, v in metadata.items())
        ]

    async def lookup(self, sandbox_id: str) -> SandboxListing | None:
        found = self.sandboxes.get(sandbox_id)
        return None if found is None else SandboxListing(sandbox_id, found[0])

    async def kill(self, sandbox_id: str) -> bool:
        if self.kill_is_noop:
            return True
        return self.sandboxes.pop(sandbox_id, None) is not None

    async def pause(self, sandbox_id: str) -> None:
        return None

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
        self._pids += 1
        inner = shlex.split(command)[-1]
        if inner.startswith("cd -- ") and ("-printf" in inner or "xargs -0" in inner):
            root = shlex.split(inner.split(" || ")[0])[2].rstrip("/")
            files = self.sandboxes[sandbox_id][1]
            if "-printf" in inner:
                out = self._listing(files, root)
            else:
                out = self._records(files, root, stdin or b"")
            return _Command(self._pids, base64.b64encode(out).decode(), 0)
        text, code = self.script.get(inner, ("", 0))
        return _Command(self._pids, text, code)

    @staticmethod
    def _listing(files: Mapping[str, bytes], root: str) -> bytes:
        """The walk's records, ``%y %n %s %d\\0%P\\0%l\\0``, for each dir and file under root."""
        under = root + "/"
        rels = [p.removeprefix(under) for p in files if p.startswith(under)]
        dirs = {posixpath.dirname(r) for r in rels} - {""}
        dirs |= {posixpath.dirname(d) for d in dirs} - {""}
        out = b""
        for rel in sorted(dirs):
            out += f"d 2 4096 {rel.count('/') + 1}\0{rel}\0\0".encode()
        for rel in sorted(rels):
            size = len(files[under + rel])
            out += f"f 1 {size} {rel.count('/') + 1}\0{rel}\0\0".encode()
        return out

    @staticmethod
    def _records(files: Mapping[str, bytes], root: str, stdin: bytes) -> bytes:
        """One read record per NUL-separated path on stdin: content, or vanished."""
        out = b""
        for rel in stdin.decode().split("\0")[:-1]:
            content = files.get(f"{root}/{rel}")
            if content is None:
                out += f"v 0\0{rel}\0".encode()
            else:
                out += f"f {len(content)}\0{rel}\0".encode() + content
        return out

    async def reconnect(self, sandbox_id: str, pid: int) -> _Command:
        return _Command(pid, "", 0)

    async def read_bytes(self, sandbox_id: str, path: str, *, user: str) -> bytes:
        try:
            return self.sandboxes[sandbox_id][1][path]
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    async def write_bytes(self, sandbox_id: str, path: str, content: bytes, *, user: str) -> None:
        self.sandboxes[sandbox_id][1][path] = content


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> E2BSettings:
    for name in ("ENABLED", "API_KEY", "TEMPLATE", "CPU_COUNT", "MEMORY_MB", "TIMEOUT_SECONDS"):
        monkeypatch.delenv(f"SYN_E2B_{name}", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(f"SYN_E2B_{name}", value)
    return E2BSettings(_env_file=None)  # type: ignore[call-arg]


def _enabled(monkeypatch: pytest.MonkeyPatch) -> E2BSettings:
    return _settings(
        monkeypatch, ENABLED="true", API_KEY=_KEY, TEMPLATE=_TEMPLATE, TIMEOUT_SECONDS="900"
    )


# --- config ---------------------------------------------------------------


def test_e2b_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _settings(monkeypatch).enabled is False


@pytest.mark.parametrize(
    ("env", "missing"),
    [
        ({"TEMPLATE": _TEMPLATE}, "SYN_E2B_API_KEY"),
        ({"API_KEY": _KEY}, "SYN_E2B_TEMPLATE"),
    ],
)
def test_enabled_without_key_or_template_refuses_to_load(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], missing: str
) -> None:
    with pytest.raises(ValidationError, match=missing):
        _settings(monkeypatch, ENABLED="true", **env)


def test_the_key_never_appears_in_settings_text(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _enabled(monkeypatch)
    assert _KEY not in repr(settings)
    assert _KEY not in str(settings.model_dump())


# --- selection ------------------------------------------------------------


def test_flag_off_selects_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    # A key and template alone do not turn E2B on.
    off = _settings(monkeypatch, API_KEY=_KEY, TEMPLATE=_TEMPLATE)
    assert WorkspaceBackend.selected(off) is WorkspaceBackend.DOCKER


def test_flag_on_with_key_selects_e2b(monkeypatch: pytest.MonkeyPatch) -> None:
    assert WorkspaceBackend.selected(_enabled(monkeypatch)) is WorkspaceBackend.E2B


def test_production_wiring_selects_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The consumer: syn-api's build_workspace_service, not the enum alone."""
    from syn_api import _wiring

    chosen: list[WorkspaceBackend] = []

    def record(_cls: type[WorkspaceService], *, backend: WorkspaceBackend, **_: object) -> None:
        chosen.append(backend)

    monkeypatch.setattr(WorkspaceService, "create", classmethod(record))
    monkeypatch.setattr(_wiring, "get_platform_token_service", lambda: None)
    from syn_adapters.workspace_backends.service import WorkspaceServiceConfig

    _settings(monkeypatch)
    _wiring.build_workspace_service(WorkspaceServiceConfig(), None)
    _enabled(monkeypatch)
    _wiring.build_workspace_service(WorkspaceServiceConfig(), None)
    assert chosen == [WorkspaceBackend.DOCKER, WorkspaceBackend.E2B]


# --- wiring ---------------------------------------------------------------


async def test_service_wires_the_e2b_provider_through_the_agentic_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    double = SandboxDouble()
    service = WorkspaceService.create(
        backend=WorkspaceBackend.E2B, e2b=_enabled(monkeypatch), e2b_client=double
    )
    assert not service.credential_policy.supplies_credentials
    isolation = service._isolation
    assert isinstance(isolation, AgenticIsolationAdapter)
    # The image the service's own config carries, as create_workspace passes it.
    handle = await isolation.create(suite.isolation_config(service._config.image))
    assert handle.isolation_type == "e2b"
    assert double.created_from == [_TEMPLATE]
    assert double.lifetimes == [900]
    await isolation.destroy(handle)
    assert double.sandboxes == {}


def test_e2b_backend_without_settings_is_refused() -> None:
    with pytest.raises(ValueError, match="E2BSettings"):
        WorkspaceService.create(backend=WorkspaceBackend.E2B)


def test_e2b_offers_the_operation_contract_agents_launch_through() -> None:
    # agentic-workspace #97 gave the E2B provider SupportsOperations, so the
    # adapter hands back the provider instead of refusing the launch.
    adapter, provider = _adapter(SandboxDouble())
    assert isinstance(provider, SupportsOperations)
    assert adapter.operations is provider


async def test_a_workspace_bigger_than_the_template_is_refused() -> None:
    double = SandboxDouble()
    adapter, _ = _adapter(double)
    with pytest.raises(WorkspaceCapacityError, match="MB of memory"):
        await adapter.create(suite.isolation_config(_TEMPLATE, memory_mb=4096))
    assert double.created_from == []


async def test_a_per_run_image_is_refused_not_ignored() -> None:
    adapter, _ = _adapter(SandboxDouble())
    config = suite.isolation_config(_TEMPLATE)
    config = type(config)(**{**config.__dict__, "image": "ghcr.io/other/image:latest"})
    with pytest.raises(WorkspaceProvisionError, match="refuses image"):
        await adapter.create(config)


class _LinkedSandboxDouble(SandboxDouble):
    """The walk also finds a symlink out of the root beside the stored files."""

    @staticmethod
    def _listing(files: Mapping[str, bytes], root: str) -> bytes:
        return SandboxDouble._listing(files, root) + b"l 1 11 2\0conformance/link\0/etc/passwd\0"


async def test_a_refused_file_fails_the_read_instead_of_going_missing() -> None:
    adapter, _ = _adapter(_LinkedSandboxDouble())
    handle = await suite.check_create(adapter, suite.isolation_config(_TEMPLATE))
    await adapter.copy_to(handle, [("conformance/blob.bin", b"kept")])
    with pytest.raises(RuntimeError, match=r"conformance/link \(escaping_symlink\)"):
        await adapter.copy_from(handle, ["conformance/*"])
    await adapter.destroy(handle)


# --- conformance over the double ------------------------------------------


def _adapter(double: SandboxDouble) -> tuple[AgenticIsolationAdapter, E2BWorkspaceProvider]:
    provider = E2BWorkspaceProvider(_TEMPLATE, client=double)
    kit = BackendKit.e2b(_TEMPLATE, cpu_count=2, memory_mb=2048)
    return AgenticIsolationAdapter(kit=kit, provider=lambda _: provider), provider


async def test_conformance_suite_over_the_double() -> None:
    adapter, provider = _adapter(SandboxDouble())
    config = suite.isolation_config(_TEMPLATE)
    labels = suite.run_labels(config)
    handle = await suite.check_create(adapter, config)
    await suite.check_merged_stream_and_outcome(adapter, handle)
    await suite.check_binary_round_trip(adapter, handle)
    await suite.check_list_and_attach(provider, handle, labels)
    await suite.check_cleanup(adapter, provider, handle, labels)


async def test_negative_control_a_noop_kill_fails_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The suite's cleanup check must be able to fail: a kill that does nothing."""
    monkeypatch.setattr(e2b_provider, "_REMOVAL_SECONDS", 0.05)
    double = SandboxDouble(kill_is_noop=True)
    adapter, provider = _adapter(double)
    config = suite.isolation_config(_TEMPLATE)
    handle = await suite.check_create(adapter, config)
    with pytest.raises(WorkspaceTeardownError, match="SandboxRemovalError"):
        await suite.check_cleanup(adapter, provider, handle, suite.run_labels(config))
    assert list(double.sandboxes) == [handle.isolation_id]
