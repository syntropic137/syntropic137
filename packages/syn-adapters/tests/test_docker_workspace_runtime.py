"""Docker-backed evidence that the recorded runtime is the one Docker enforces.

Real ``WorkspaceDockerProvider``, real container. Run with:

    uv run pytest -m integration packages/syn-adapters/tests/test_docker_workspace_runtime.py

The tests pull a digest-pinned busybox themselves, so a clean host with a
Docker daemon needs nothing else; ``SYN_CONTRACT_TEST_IMAGE`` overrides the
image with any other that has ``sh``. With no daemon, or an image that cannot
be pulled, they fail with the reason. They never skip: a skipped run is
indistinguishable from evidence nobody collected (PC-193).

The unit tests prove the setting reaches ``SecurityConfig.runtime`` and that
``Workspace.metadata`` is read back. This proves the last hop neither can see:
what syn records from that metadata is the runtime ``docker inspect`` reports
for the container.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from agentic_isolation import SecurityConfig, Workspace, WorkspaceConfig, WorkspaceDockerProvider
from agentic_isolation.providers.docker import ContainerRemovalError

from syn_adapters.workspace_backends.agentic.runtime_mapping import (
    isolation_runtime_from_metadata,
    resolve_host_runtime,
    to_aw_runtime,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationRuntime,
)
from syn_shared.settings.workspace import WorkspaceRuntime

if TYPE_CHECKING:
    from pathlib import Path

    from agentic_isolation.providers.teardown_report import TeardownReport

# busybox:1.36.1, multi-arch index digest: the bytes cannot move under the tag.
_PINNED_IMAGE = "busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662"
IMAGE = os.environ.get("SYN_CONTRACT_TEST_IMAGE") or _PINNED_IMAGE

# What the Docker CLI prints when the object is absent, and only then.
_NO_SUCH_CONTAINER = "No such container"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        pytest.fail(f"docker CLI not found on PATH; these tests need a Docker host: {e}")


@pytest.fixture(scope="module")
def _image_present() -> None:
    """Provision IMAGE on this host, or fail saying why it could not."""
    info = _docker("info", "--format", "{{.ServerVersion}}")
    if info.returncode != 0:
        pytest.fail(f"Docker daemon unreachable (docker info): {info.stderr.strip()}")
    if _docker("image", "inspect", IMAGE).returncode == 0:
        return
    pull = _docker("pull", IMAGE)
    if pull.returncode != 0:
        pytest.fail(f"Could not pull {IMAGE}: {pull.stderr.strip()}")


async def _recorded_and_enforced(
    tmp_path: Path, requested: WorkspaceRuntime | None
) -> tuple[IsolationRuntime | None, str, str]:
    """Create one container; return syn's record, its alias, and Docker's HostConfig.Runtime.

    The runtime rides on ``WorkspaceConfig.security``, as
    ``AgenticIsolationAdapter.create`` sends it. The provider's own ``security``
    is never consulted once a config is passed: that field defaults to an
    instance, so a request made only on the provider resolves as auto.
    """
    security = SecurityConfig(runtime=to_aw_runtime(requested))
    provider = WorkspaceDockerProvider(
        default_image=IMAGE,
        default_network="none",
        workspace_base_dir=tmp_path / "workspaces",
        security=security,
    )
    workspace = await provider.create(
        WorkspaceConfig(provider="docker", image=IMAGE, security=security)
    )
    container = workspace.metadata.get("container_id", workspace.id)
    try:
        inspected = json.loads(
            subprocess.run(
                ["docker", "inspect", container], capture_output=True, text=True, check=True
            ).stdout
        )[0]
        return (
            isolation_runtime_from_metadata(workspace.metadata),
            workspace.metadata["runtime_alias"],
            inspected["HostConfig"]["Runtime"],
        )
    finally:
        await _teardown_and_confirm_removed(provider, workspace, container)


async def _teardown_and_confirm_removed(
    provider: WorkspaceDockerProvider, workspace: Workspace, container: str
) -> None:
    """Tear the workspace down, then prove with Docker that the container is gone.

    The Docker check sits in a ``finally`` so it runs exactly when it matters
    most: a teardown that raises (AW's ``ContainerRemovalError``) is the case
    most likely to leave a container behind. Its error still propagates, and a
    cleanup failure raised here chains onto it rather than replacing it.
    """
    try:
        report = await provider.teardown(target=workspace)
    finally:
        _assert_removed(container)
    assert report.finalization.state == "completed"


def _assert_removed(container: str) -> None:
    """Fail unless Docker confirms ``container`` no longer exists, removing it first.

    A teardown that does not raise can still retain the workspace, so the
    report alone is not proof the container is gone; ``docker inspect`` is.
    Only "No such container" counts as absence: an inspect that fails for any
    other reason (daemon unreachable, permission denied) proves nothing.
    """
    inspect = _docker("container", "inspect", container)
    if inspect.returncode != 0:
        if _NO_SUCH_CONTAINER in inspect.stderr:
            return
        pytest.fail(
            f"could not confirm container {container} was removed: {inspect.stderr.strip()}"
        )
    removal = _docker("rm", "-f", container)
    if removal.returncode != 0:
        pytest.fail(
            f"teardown left container {container} behind and `docker rm -f` failed: "
            f"{removal.stderr.strip()}"
        )
    pytest.fail(f"teardown left container {container} behind; removed it with `docker rm -f`")


@pytest.mark.integration
@pytest.mark.usefixtures("_image_present")
async def test_explicit_runc_is_recorded_and_enforced(tmp_path: Path) -> None:
    recorded, _, enforced = await _recorded_and_enforced(tmp_path, WorkspaceRuntime.RUNC)

    assert recorded == IsolationRuntime(
        requested=WorkspaceRuntime.RUNC, effective=WorkspaceRuntime.RUNC
    )
    assert enforced == "runc"


@pytest.mark.integration
@pytest.mark.usefixtures("_image_present")
async def test_auto_records_the_runtime_docker_ran(tmp_path: Path) -> None:
    """Auto on any host: the record is AW's resolution, and Docker enforced it.

    The expected runtime is asked of agentic-workspace's resolver for this
    host, never inferred from the alias name, so a record that disagrees with
    the resolver fails even when the alias matches.
    """
    expected = resolve_host_runtime(None)
    recorded, alias, enforced = await _recorded_and_enforced(tmp_path, None)

    assert expected.error is None
    assert recorded == IsolationRuntime(requested=None, effective=expected.effective)
    assert alias == expected.alias
    assert enforced == alias


# The cleanup path itself, with Docker's CLI replaced so each failure can be
# produced on demand. These run in the unit gate: the Docker tests above only
# reach this path when a real teardown goes wrong.

_GONE = subprocess.CompletedProcess[str]([], 1, "", f"Error: {_NO_SUCH_CONTAINER}: c1")
_PRESENT = subprocess.CompletedProcess[str]([], 0, "[{}]", "")
_REMOVED = subprocess.CompletedProcess[str]([], 0, "c1", "")
_DAEMON_DOWN = subprocess.CompletedProcess[str](
    [], 1, "", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
)


def _fake_docker(
    monkeypatch: pytest.MonkeyPatch,
    inspect: subprocess.CompletedProcess[str],
    rm: subprocess.CompletedProcess[str] = _REMOVED,
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return rm if args[0] == "rm" else inspect

    monkeypatch.setattr(sys.modules[__name__], "_docker", docker)
    return calls


def _failing_teardown(tmp_path: Path) -> tuple[WorkspaceDockerProvider, Workspace]:
    provider = WorkspaceDockerProvider(workspace_base_dir=tmp_path)

    async def teardown(target: Workspace) -> TeardownReport:
        raise ContainerRemovalError(f"docker rm failed for {target.id}")

    provider.teardown = teardown  # type: ignore[method-assign]  # inject AW's removal failure
    workspace = Workspace(
        id="c1", provider="docker", path=tmp_path, config=WorkspaceConfig(provider="docker")
    )
    return provider, workspace


@pytest.mark.unit
async def test_raising_teardown_still_removes_the_container_and_keeps_its_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_docker(monkeypatch, inspect=_PRESENT)
    provider, workspace = _failing_teardown(tmp_path)

    with pytest.raises(pytest.fail.Exception, match="left container c1 behind") as failed:
        await _teardown_and_confirm_removed(provider, workspace, "c1")

    assert ("rm", "-f", "c1") in calls
    assert isinstance(failed.value.__context__, ContainerRemovalError)


@pytest.mark.unit
async def test_raising_teardown_with_container_gone_propagates_the_teardown_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_docker(monkeypatch, inspect=_GONE)
    provider, workspace = _failing_teardown(tmp_path)

    with pytest.raises(ContainerRemovalError):
        await _teardown_and_confirm_removed(provider, workspace, "c1")

    assert calls == [("container", "inspect", "c1")]


@pytest.mark.unit
def test_failed_inspection_is_not_proof_of_removal(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(monkeypatch, inspect=_DAEMON_DOWN)

    with pytest.raises(pytest.fail.Exception, match="could not confirm container c1"):
        _assert_removed("c1")


@pytest.mark.unit
def test_failed_forced_removal_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(monkeypatch, inspect=_PRESENT, rm=_DAEMON_DOWN)

    with pytest.raises(pytest.fail.Exception, match="`docker rm -f` failed: Cannot connect"):
        _assert_removed("c1")


@pytest.mark.unit
def test_confirmed_absence_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_docker(monkeypatch, inspect=_GONE)

    _assert_removed("c1")

    assert calls == [("container", "inspect", "c1")]
