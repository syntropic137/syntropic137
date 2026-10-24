"""An agent launches on an E2B workspace through the BackendKit (#1912).

The whole production path, from ``WorkspaceService.create(backend=E2B)``
through ``create_workspace`` and ``ManagedWorkspace.stream`` into the real
``AgenticEventStreamAdapter``, against the real ``E2BWorkspaceProvider`` over
``SandboxDouble``. Only the provider's four operation methods are scripted:
the double cannot speak the operation launch protocol, and what is under test
is what Syn137 hands the provider, not how E2B runs it.

The scripted ``start`` resolves credential bindings exactly as agentic-workspace's
E2B provider does: through the resolver it was constructed with, refused as
``rejected_policy`` when it was given none (AW providers/e2b_operations.py).
That refusal is the defect #1912 fixed in Syn137's wiring.
"""

from __future__ import annotations

import asyncio
import base64
from typing import TYPE_CHECKING, ClassVar

import pytest
from agentic_isolation.contract import (
    MISSING,
    LaunchMarker,
    ObservationPage,
    OperationError,
    OperationRef,
    OperationStatus,
    WorkspaceRef,
)
from agentic_isolation.providers.e2b import E2BWorkspaceProvider
from agentic_isolation.providers.operation_spool import OperationFailure

from syn_adapters.workspace_backends.e2b.test_e2b_backend import (
    _KEY,
    _TEMPLATE,
    SandboxDouble,
    _settings,
)
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService

if TYPE_CHECKING:
    from agentic_isolation.contract import OperationSpec
    from agentic_isolation.providers.base import CredentialResolver, Workspace

pytestmark = pytest.mark.unit

_AGENT = ["claude", "-p", "hello", "--output-format", "stream-json"]
_LINE = b'{"type":"system","subtype":"init"}\n'
#: Not a value any default produces: only the fake's outcome can put it there.
_EXIT = 7
#: Named a credential by agentic-workspace's rules, so it must travel as a binding.
_CREDENTIAL = ("SYN_API_TOKEN", "syn137-launch-credential-not-real")


class ScriptedE2BProvider(E2BWorkspaceProvider):
    """The real E2B provider, its operations scripted and recorded."""

    built: ClassVar[list[ScriptedE2BProvider]] = []

    def __init__(
        self, template: str, *, credentials: CredentialResolver | None = None, **kw: object
    ) -> None:
        super().__init__(template, credentials=credentials, **kw)  # type: ignore[arg-type]
        self.resolver = credentials
        self.specs: list[OperationSpec] = []
        self.delivered: dict[str, str] = {}
        self.cancelled: list[float] = []
        self.hang = False
        self._state = "running"
        ScriptedE2BProvider.built.append(self)

    async def start(self, workspace: Workspace, spec: OperationSpec) -> OperationRef:
        for binding in spec.credential_bindings:
            if self.resolver is None:
                raise OperationFailure(
                    OperationError(
                        kind="rejected_policy",
                        message="credential bindings need a CredentialResolver; none was injected",
                    )
                )
            self.delivered[binding.target] = await self.resolver.resolve(binding.ref)
        self.specs.append(spec)
        return OperationRef(
            workspace=WorkspaceRef(schema=MISSING, provider="e2b", resource_id=workspace.id),
            operation_id=f"{workspace.id}-op1",
            operation_key=spec.operation_key,
        )

    async def observe(
        self, ref: OperationRef, *, cursor: str | None, max_bytes: int, wait_seconds: float = 0
    ) -> ObservationPage:
        index = int(cursor or 0)
        if self.hang and self._state == "running" and index > 0:
            await asyncio.sleep(0.01)
        complete = not self.hang or self._state != "running"
        data = _LINE if index == 0 else b""
        return ObservationPage(
            schema=MISSING,
            ref=ref,
            state="running" if not complete else self._final_state(),  # type: ignore[arg-type]
            cursor=str(index),
            next_cursor=str(index + 1),
            data_b64=base64.b64encode(data).decode(),
            gap=MISSING,
            complete=complete,
        )

    def _final_state(self) -> str:
        return "cancelled" if self.cancelled else "succeeded" if not _EXIT else "failed"

    async def status(self, ref: OperationRef) -> OperationStatus:
        return OperationStatus(
            schema=MISSING,
            ref=ref,
            state=self._final_state(),  # type: ignore[arg-type]
            exit_code=143 if self.cancelled else _EXIT,
            execution_id=ref.workspace.resource_id,
            metadata={},
        )

    async def cancel(self, ref: OperationRef, *, grace_seconds: float) -> OperationStatus:
        self.cancelled.append(grace_seconds)
        self._state = "cancelled"
        return await self.status(ref)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> WorkspaceService:
    ScriptedE2BProvider.built.clear()
    # Where the production factory imports the provider from.
    monkeypatch.setattr("agentic_isolation.E2BWorkspaceProvider", ScriptedE2BProvider)
    # A template as big as the service's default workspace: the default
    # template (2048 MB) refuses it.
    e2b = _settings(monkeypatch, ENABLED="true", API_KEY=_KEY, TEMPLATE=_TEMPLATE, MEMORY_MB="4096")
    return WorkspaceService.create(
        backend=WorkspaceBackend.E2B, e2b=e2b, e2b_client=SandboxDouble()
    )


async def test_the_agent_launches_through_the_e2b_provider(service: WorkspaceService) -> None:
    async with service.create_workspace("exec-1912", with_sidecar=False) as workspace:
        lines = [
            line
            async for line in workspace.stream(
                _AGENT, environment=dict([_CREDENTIAL]), wrapper_name="syn-launch-1912"
            )
        ]
        (provider,) = ScriptedE2BProvider.built
        (spec,) = provider.specs
        assert workspace.isolation_handle.isolation_type == "e2b"
        # The sandbox argv, exactly: no docker exec prefix, no credential in it.
        assert spec.argv == tuple(_AGENT)
        assert _CREDENTIAL[1] not in " ".join(spec.argv)
        assert _CREDENTIAL[0] not in spec.environment
        # The launch marker and the credential travel through the provider.
        assert spec.launch_marker == LaunchMarker(
            argv0="syn-launch-1912", line=spec.launch_marker.line
        )
        assert provider.delivered == dict([_CREDENTIAL])
        assert lines == [_LINE.decode().strip()]
        assert workspace.last_stream_exit_code == _EXIT


async def test_cancelling_the_agent_cancels_the_e2b_operation(service: WorkspaceService) -> None:
    async with service.create_workspace("exec-1912", with_sidecar=False) as workspace:
        (provider,) = ScriptedE2BProvider.built
        provider.hang = True
        stream = workspace.stream(_AGENT)
        assert await anext(stream) == _LINE.decode().strip()  # type: ignore[call-overload]
        assert await workspace.interrupt() is True
        assert provider.cancelled
        async for _ in stream:  # type: ignore[attr-defined]
            pass
        assert workspace.last_stream_exit_code == 143
