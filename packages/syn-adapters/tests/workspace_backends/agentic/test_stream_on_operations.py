"""The agent stream runs on the provider operation contract (plan §5.3, §7 row 7).

Driven through a recording double of `SupportsOperations`, so every assertion
is about what the stream adapter ASKED the provider for and what it made of
the pages it got back. The double serves pages it is told to, which is how a
page boundary can be put mid-code-point, mid-line or across a gap.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import pytest
from agentic_events import EventEmitter, Recording
from agentic_isolation import WorkspaceConfig
from agentic_isolation.contract import (
    MISSING,
    ObservationGap,
    ObservationPage,
    OperationError,
    OperationRef,
    OperationSpec,
    OperationStatus,
    WorkspaceRef,
)
from agentic_isolation.providers.base import Workspace
from agentic_isolation.providers.docker_operations import DockerOperations
from agentic_isolation.providers.operation_spool import OperationFailure
from pydantic import ValidationError

from syn_adapters.platform_access import WorkspacePlatformGrant
from syn_adapters.workspace_backends.agentic import stream_adapter
from syn_adapters.workspace_backends.agentic.credential_scrubber import REDACTED_MARKER
from syn_adapters.workspace_backends.agentic.credentials import WorkspaceCredentials
from syn_adapters.workspace_backends.agentic.stream_adapter import (
    AgenticEventStreamAdapter,
    LineDecoder,
)
from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter
from syn_domain.contexts.orchestration import announce_as
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    AgentLaunchEvidence,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_shared.in_memory import InMemoryAdapter
from syn_shared.settings.session_store import SessionStoreSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
        ObservationType,
    )

pytestmark = pytest.mark.unit

_TOKEN = "synpt_SYNTHETIC_MARKER_NOT_A_CREDENTIAL"
_WS = WorkspaceRef(schema=MISSING, provider="recording", resource_id="ws-1")


class RecordingOperations(InMemoryAdapter):
    """`SupportsOperations` that records each call and serves scripted pages.

    `start` resolves the spec's credential bindings through the injected
    resolver, as a real provider does, and keeps what it would have put in the
    workload's environment so a test can prove the value arrived there.
    """

    def __init__(
        self,
        credentials: WorkspaceCredentials,
        pages: Sequence[bytes | int | None],
        *,
        state: str = "succeeded",
        exit_code: int | None = 0,
        signal: str | None = None,
    ) -> None:
        super().__init__()
        self._credentials = credentials
        # bytes = a data page; int = a gap of that many lost bytes; None = a gap of unknown size.
        self._pages = list(pages)
        self._state = state
        self._exit_code = exit_code
        self._signal = signal
        self.specs: list[OperationSpec] = []
        self.workload_env: dict[str, str] = {}
        self.cancelled = False
        self.calls: list[str] = []

    def _ref(self, spec: OperationSpec) -> OperationRef:
        return OperationRef(workspace=_WS, operation_id="op-1", operation_key=spec.operation_key)

    async def start(self, workspace: Workspace, spec: OperationSpec) -> OperationRef:
        self.calls.append("start")
        self.specs.append(spec)
        self.workload_env = dict(spec.environment)
        for binding in spec.credential_bindings:
            self.workload_env[binding.target] = await self._credentials.resolve(binding.ref)
        return self._ref(spec)

    async def observe(
        self, ref: OperationRef, *, cursor: str | None, max_bytes: int, wait_seconds: float = 0
    ) -> ObservationPage:
        self.calls.append("observe")
        index = int(cursor or 0)
        item = self._pages[index]
        complete = index == len(self._pages) - 1
        data = item if isinstance(item, bytes) else b""
        gap: Any = MISSING
        if not isinstance(item, bytes):
            gap = ObservationGap(lost_bytes=item)
        return ObservationPage(
            schema=MISSING,
            ref=ref,
            state=self._state if complete else "running",  # type: ignore[arg-type]
            cursor=str(index),
            next_cursor=str(index + 1),
            data_b64=base64.b64encode(data).decode(),
            gap=gap,
            complete=complete,
        )

    async def status(self, ref: OperationRef) -> OperationStatus:
        self.calls.append("status")
        return OperationStatus(
            schema=MISSING,
            ref=ref,
            state=self._state,  # type: ignore[arg-type]
            exit_code=self._exit_code,
            signal=self._signal,
            execution_id="ws-1",
            metadata={},
        )

    async def cancel(self, ref: OperationRef, *, grace_seconds: float) -> OperationStatus:
        self.calls.append("cancel")
        self.cancelled = True
        self._state = "cancelled"
        return await self.status(ref)


class _Host:
    def __init__(self, operations: RecordingOperations, credentials: WorkspaceCredentials) -> None:
        self.operations = operations
        self.credentials = credentials

    def workspace(self, isolation_id: str) -> Workspace | None:
        return Workspace(
            id=isolation_id,
            provider="recording",
            path=Path("/nonexistent"),
            config=WorkspaceConfig(),
        )


def _credentials() -> WorkspaceCredentials:
    return WorkspaceCredentials(SessionStoreSettings())


def _stream(
    pages: Sequence[bytes | int | None],
    *,
    state: str = "succeeded",
    exit_code: int | None = 0,
    signal: str | None = None,
) -> tuple[AgenticEventStreamAdapter, RecordingOperations, WorkspaceCredentials]:
    credentials = _credentials()
    ops = RecordingOperations(credentials, pages, state=state, exit_code=exit_code, signal=signal)
    return AgenticEventStreamAdapter(_Host(ops, credentials)), ops, credentials  # type: ignore[arg-type]


_HANDLE = IsolationHandle(isolation_id="ws-1", isolation_type="docker")


async def _lines(
    adapter: AgenticEventStreamAdapter,
    *,
    environment: dict[str, str] | None = None,
    working_directory: str | None = None,
    timeout_seconds: float | None = None,
) -> list[str]:
    stream = adapter.stream(
        _HANDLE,
        ["claude", "-p", "hi"],
        environment=environment,
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,  # type: ignore[arg-type]
    )
    return [line async for line in stream]


async def test_the_stream_path_never_spawns_a_process(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("the stream path reached asyncio.create_subprocess_exec")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    adapter, ops, _ = _stream([b'{"type":"result"}\n'])

    assert await _lines(adapter) == ['{"type":"result"}']
    assert ops.calls[0] == "start" and ops.calls[-1] == "status"


async def test_environment_and_platform_grant_reach_the_workload_but_not_the_spec() -> None:
    grant = WorkspacePlatformGrant("http://envoy-proxy:8081/syn-platform", _TOKEN)
    adapter, ops, credentials = _stream([b"x\n"])

    await _lines(
        adapter, environment={"PHASE": "p1", **grant.env}, working_directory="/workspace/repo"
    )

    spec = ops.specs[0]
    assert ops.workload_env == {"PHASE": "p1", **grant.env}, "every value reaches the workload"
    assert _TOKEN not in spec.model_dump_json(), "the token is bound by ref, never carried by value"
    assert [b.target for b in spec.credential_bindings] == ["SYN_API_TOKEN"]
    assert spec.environment["SYN_API_URL"] == grant.api_url
    assert spec.working_directory == "repo"
    with pytest.raises(Exception, match="not one Syntropic137 binds"):
        await credentials.resolve(spec.credential_bindings[0].ref)  # released after start


async def test_every_credential_agentic_workspace_names_is_bound_never_carried() -> None:
    """AUTH as a whole word is a credential too (AW's WorkspaceConfig rule), not only *_TOKEN."""
    store = "SYNTHETIC_STORE_AUTH_NOT_A_CREDENTIAL"
    grant = WorkspacePlatformGrant("http://envoy-proxy:8081/syn-platform", _TOKEN)
    environment = {
        "AGENTIC_SESSION_STORE_AUTH": store,
        "GIT_AUTHOR_NAME": "syn-bot",
        **grant.env,
    }
    adapter, ops, _ = _stream([b"x\n"])

    await _lines(adapter, environment=environment)

    spec = ops.specs[0]
    assert ops.workload_env == environment, "every value reaches the workload"
    assert sorted(b.target for b in spec.credential_bindings) == [
        "AGENTIC_SESSION_STORE_AUTH",
        "SYN_API_TOKEN",
    ]
    assert spec.environment["GIT_AUTHOR_NAME"] == "syn-bot", "AUTHOR is not AUTH"
    # The argv agentic-workspace's real Docker transport would spawn for this spec.
    argv = DockerOperations(
        credentials=None, retention_bytes=1024, max_page_bytes=1024
    ).client_argv(
        "ws-container", spec, secret_names=tuple(b.target for b in spec.credential_bindings)
    )
    for value in (store, _TOKEN):
        assert value not in spec.model_dump_json()
        assert not any(value in arg for arg in argv)


async def test_a_spec_that_fails_validation_parks_no_launch_credential() -> None:
    adapter, ops, credentials = _stream([b"x\n"])
    stream = adapter.stream(_HANDLE, [], environment={"SYN_API_TOKEN": _TOKEN})

    with pytest.raises(ValidationError):
        _ = [line async for line in stream]

    assert ops.specs == []
    assert not credentials._launch


async def test_a_start_that_fails_parks_no_launch_credential() -> None:
    adapter, ops, credentials = _stream([b"x\n"])
    refused = OperationFailure(OperationError(kind="provider_unavailable", message="no daemon"))

    async def failed_start(*_a: object, **_k: object) -> None:
        raise refused

    ops.start = failed_start  # type: ignore[method-assign]
    with pytest.raises(OperationFailure) as caught:
        await _lines(adapter, environment={"SYN_API_TOKEN": _TOKEN})

    assert caught.value is refused
    assert not credentials._launch


async def test_an_observation_failure_stays_primary_when_cancel_also_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, ops, _ = _stream([b"x\n"])
    primary = OperationFailure(OperationError(kind="provider_unavailable", message="observe"))
    secondary = OperationFailure(OperationError(kind="provider_unavailable", message="cancel"))

    async def failed_observe(*_a: object, **_k: object) -> None:
        raise primary

    async def failed_cancel(*_a: object, **_k: object) -> None:
        ops.calls.append("cancel")
        raise secondary

    ops.observe = failed_observe  # type: ignore[method-assign]
    ops.cancel = failed_cancel  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR), pytest.raises(OperationFailure) as caught:
        await _lines(adapter)

    assert caught.value is primary
    assert "cancel" in ops.calls, "the operation was still told to stop"
    assert "provider_unavailable: cancel" in caplog.text, "the secondary failure is surfaced"


async def test_a_status_failure_with_no_primary_error_still_propagates() -> None:
    adapter, ops, _ = _stream([b"x\n"])
    lost = OperationFailure(OperationError(kind="provider_unavailable", message="status"))

    async def failed_status(*_a: object, **_k: object) -> None:
        raise lost

    ops.status = failed_status  # type: ignore[method-assign]
    with pytest.raises(OperationFailure) as caught:
        await _lines(adapter)

    assert caught.value is lost
    assert ops.cancelled


async def test_the_launch_marker_is_the_one_the_evidence_counts() -> None:
    launches = 0

    async def observer() -> None:
        nonlocal launches
        launches += 1

    evidence = AgentLaunchEvidence(observer)
    announcement = announce_as(evidence.wrapper_name)
    adapter, ops, _ = _stream([f"{announcement}\n".encode(), b'{"type":"result"}\n'])

    survived = [
        line
        async for line in evidence.observing(
            adapter.stream(_HANDLE, ["claude"], wrapper_name=evidence.wrapper_name)
        )
    ]
    await evidence.settle(adapter.last_exit_code)

    marker = ops.specs[0].launch_marker
    assert marker is not MISSING
    assert (marker.argv0, marker.line) == (evidence.wrapper_name, announcement)
    assert evidence.wrapper_name not in ops.specs[0].argv, "the name the agent could forge"
    assert evidence.wrapper_name not in ops.specs[0].environment.values()
    assert survived == ['{"type":"result"}']
    assert launches == 1


async def test_a_forged_announcement_under_another_name_does_not_count() -> None:
    launches = 0

    async def observer() -> None:
        nonlocal launches
        launches += 1

    evidence = AgentLaunchEvidence(observer)
    forged = announce_as("not-the-wrapper-we-named")
    adapter, _, _ = _stream([f"{forged}\n".encode()], state="failed", exit_code=127)

    _ = [
        line
        async for line in evidence.observing(
            adapter.stream(_HANDLE, ["claude"], wrapper_name=evidence.wrapper_name)
        )
    ]
    await evidence.settle(adapter.last_exit_code)

    assert launches == 0


async def test_exit_status_survives() -> None:
    adapter, _, _ = _stream([b"x\n"], state="failed", exit_code=3)
    await _lines(adapter)
    assert adapter.last_exit_code == 3
    assert adapter.last_signal_death is None


async def test_signal_death_survives_and_carries_no_credential(
    caplog: pytest.LogCaptureFixture,
) -> None:
    grant = WorkspacePlatformGrant("http://envoy-proxy:8081/syn-platform", _TOKEN)
    adapter, _, _ = _stream([b"{}\n"], state="failed", exit_code=None, signal="SIGSEGV")

    with caplog.at_level(logging.ERROR):
        await _lines(adapter, environment=grant.env)

    assert adapter.last_exit_code == 139
    death = adapter.last_signal_death
    assert death is not None
    assert "claude" in death.command
    assert _TOKEN not in " ".join(death.command)
    assert _TOKEN not in caplog.text
    assert "SIGSEGV" in caplog.text


async def test_a_timed_out_success_reports_the_timeout_status() -> None:
    adapter, ops, _ = _stream([b"x\n"], state="timed_out", exit_code=0)
    await _lines(adapter, timeout_seconds=1.2)
    assert adapter.last_exit_code == stream_adapter._TIMEOUT_EXIT_CODE
    assert ops.specs[0].timeout_seconds == 2, "rounded up, never cut short"


async def test_a_reader_that_stops_early_cancels_the_operation() -> None:
    adapter, ops, _ = _stream([b"a\n", b"b\n", b"c\n"])
    agen = adapter.stream(_HANDLE, ["claude"])
    assert await agen.__anext__() == "a"
    await agen.aclose()
    assert ops.cancelled


_SNOWMAN = "☃".encode()  # three bytes


@pytest.mark.parametrize("cut", range(1, 12))
async def test_a_page_split_anywhere_decodes_to_the_same_lines(cut: int) -> None:
    whole = b'{"a":"' + _SNOWMAN + b'"}\n{"b":1}\nlast'
    adapter, _, _ = _stream([whole[:cut], whole[cut:]])
    assert await _lines(adapter) == ['{"a":"☃"}', '{"b":1}', "last"]


def test_line_decoder_holds_a_split_code_point() -> None:
    decoder = LineDecoder()
    assert decoder.feed(b"x" + _SNOWMAN[:1]) == []
    assert decoder.feed(_SNOWMAN[1:] + b"\r\n") == ["x☃"]
    assert decoder.finish() == []


@pytest.mark.parametrize(("gap", "expected"), [(42, 42), (None, -1)])
async def test_an_observation_gap_is_surfaced_never_silent(
    gap: int | None, expected: int, caplog: pytest.LogCaptureFixture
) -> None:
    adapter, _, _ = _stream([b'{"a":1}\n{"trunc', gap, b'ated":1}\n{"b":2}\n'])

    with caplog.at_level(logging.ERROR):
        lines = await _lines(adapter)

    assert adapter.last_observation_lost_bytes == expected
    assert "LOST" in caplog.text
    # The line the gap severed is dropped, not glued to bytes from after the gap.
    assert lines == ['{"a":1}', 'ated":1}', '{"b":2}']


async def test_embedded_hook_jsonl_passes_through_unchanged() -> None:
    """ADR-043: hook JSONL arrives inside tool_result content and must survive byte-for-byte."""
    recorded = [
        '{"type":"system","subtype":"init","session_id":"s1"}',
        '{"type":"user","message":{"content":[{"type":"tool_result","content":'
        '"{\\"event_type\\":\\"git_commit\\",\\"context\\":{\\"git\\":{\\"sha\\":\\"abc\\"}}}\\n"}]}}',
        '{"type":"result","subtype":"success","usage":{"input_tokens":1}}',
    ]
    blob = ("\n".join(recorded) + "\n").encode()
    pages = [blob[i : i + 7] for i in range(0, len(blob), 7)]
    adapter, _, _ = _stream(pages)
    assert await _lines(adapter) == recorded


# A recorded run yields the same events read directly or through provider pages.
# The "before" path feeds a recording's lines straight into the production
# `EventStreamProcessor`; the "after" path serves the same bytes as observation
# pages cut at awkward boundaries and reads them back through the stream
# adapter. Every observation - tool lifecycle, tokens, and the git hook event
# embedded in a tool_result (ADR-043) - must come out identical, in order.


@dataclass(frozen=True)
class _Observation:
    """One recorded observation; its data is kept as canonical JSON so it compares exactly."""

    kind: str
    session_id: str
    data_json: str


@dataclass
class _Observations:
    recorded: list[_Observation] = field(default_factory=list)

    async def record_observation(
        self,
        session_id: str,
        observation_type: ObservationType | str,
        data: object,
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        kind = getattr(observation_type, "value", str(observation_type))
        data_json = json.dumps(data, sort_keys=True, default=str)
        self.recorded.append(_Observation(kind, session_id, data_json))


class _Workspace:
    async def interrupt(self) -> bool:
        return True


def _hook_tool_lines() -> list[str]:
    """A Bash tool whose output carries the commit event the git hook's producer emits."""
    buffer = io.StringIO()
    EventEmitter(session_id="s-1", provider="claude", output=buffer).git_commit(
        message="feat: x", sha="abc123", branch="feat", repo="api"
    )
    use = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t-hook",
                    "name": "Bash",
                    "input": {"command": "git commit"},
                }
            ]
        },
    }
    result = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t-hook",
                    "content": f"[feat abc123] feat: x\n{buffer.getvalue()}",
                    "is_error": False,
                }
            ]
        },
    }
    return [json.dumps(use), json.dumps(result)]


async def _recorded_lines(recording: Recording) -> list[str]:
    lines = [line async for line in RecordingEventStreamAdapter(recording).stream(_HANDLE, [])]
    # The hook tool goes before the final result line, where a real run puts it.
    return [*lines[:-1], *_hook_tool_lines(), lines[-1]]


async def _process(
    lines: AsyncIterator[str],
) -> tuple[list[_Observation], tuple[int, int, int]]:
    observations = _Observations()
    tokens = TokenAccumulator()
    processor = EventStreamProcessor(
        tokens=tokens,
        subagents=SubagentTracker(),
        observability=observations,
        controller=None,
        execution_id="exec-eq",
        phase_id="phase-eq",
        session_id="s-1",
        workspace_id="ws-1",
        agent_model="claude-sonnet",
    )
    result = await processor.process_stream(lines, _Workspace())
    return observations.recorded, (result.line_count, tokens.input_tokens, tokens.output_tokens)


async def _direct(lines: list[str]) -> AsyncIterator[str]:
    for line in lines:
        yield line


@pytest.mark.parametrize("recording", [Recording.MULTI_TOOL, Recording.CONTEXT_TRACKING])
@pytest.mark.parametrize("page_bytes", [1, 7, 4093])
async def test_a_recorded_run_yields_the_same_events_through_provider_pages(
    recording: Recording, page_bytes: int
) -> None:
    lines = await _recorded_lines(recording)
    blob = ("\n".join(lines) + "\n").encode()
    pages = [blob[i : i + page_bytes] for i in range(0, len(blob), page_bytes)]
    adapter, _, _ = _stream(pages)

    before = await _process(_direct(lines))
    after = await _process(adapter.stream(_HANDLE, ["claude"]))

    kinds = [observation.kind for observation in before[0]]
    assert "git_commit" in kinds, "the embedded hook event is among those compared"
    assert kinds.count("tool_execution_started") >= 2
    assert after == before


# #1927: a credential value the workload prints never leaves the stream
# boundary, in any encoding, wherever a page boundary cuts it. Asserted on what
# CONSUMES the stream - the yielded lines, the Lane 2 tool events the production
# processor records from them, and every log line - not on the scrubber alone.

_CANARY = "ghs_CANARY/0b6f2c+Zq9"  # 21 chars: base64 with no padding; '/' and '+' URL-encode
_NEAR_MISS = "ghs_CANARY/0b6f2c+Zq8"
_LEAKED_FORMS = {
    "raw": _CANARY,
    "base64": base64.b64encode(_CANARY.encode()).decode(),
    "url-encoded": quote(_CANARY, safe=""),
}


def _printed(form: str) -> bytes:
    return f"prefix {form} suffix\n".encode()


def _assert_no_form_of_the_canary(text: str) -> None:
    for name, form in _LEAKED_FORMS.items():
        assert form not in text, f"the {name} canary leaked"


@pytest.mark.parametrize("form", sorted(_LEAKED_FORMS))
async def test_a_printed_launch_credential_never_reaches_a_yielded_line(form: str) -> None:
    adapter, _, _ = _stream([_printed(_LEAKED_FORMS[form])])

    lines = await _lines(adapter, environment={"SYN_API_TOKEN": _CANARY})

    _assert_no_form_of_the_canary("\n".join(lines))
    assert lines == [f"prefix {REDACTED_MARKER} suffix"]


@pytest.mark.parametrize("form", sorted(_LEAKED_FORMS))
async def test_a_credential_split_across_two_pages_is_still_redacted(form: str) -> None:
    printed = _printed(_LEAKED_FORMS[form])
    cut = len(b"prefix ") + len(_LEAKED_FORMS[form]) // 2
    adapter, _, _ = _stream([printed[:cut], printed[cut:]])

    lines = await _lines(adapter, environment={"SYN_API_TOKEN": _CANARY})

    assert lines == [f"prefix {REDACTED_MARKER} suffix"]


async def test_a_near_miss_and_the_launch_marker_are_untouched() -> None:
    wrapper = "syn-wrapper-1927"
    marker = announce_as(wrapper)
    adapter, _, _ = _stream([f"{marker}\n".encode(), _printed(_NEAR_MISS)])

    lines = [
        line
        async for line in adapter.stream(
            _HANDLE, ["claude"], environment={"SYN_API_TOKEN": _CANARY}, wrapper_name=wrapper
        )
    ]

    assert lines == [marker, f"prefix {_NEAR_MISS} suffix"], "byte-identical (#1879)"


async def test_the_session_store_token_is_redacted_without_being_in_the_environment() -> None:
    credentials = WorkspaceCredentials(
        SessionStoreSettings(_env_file=None, auth_token=_CANARY)  # type: ignore[arg-type]
    )
    ops = RecordingOperations(credentials, [_printed(_CANARY)])
    adapter = AgenticEventStreamAdapter(_Host(ops, credentials))  # type: ignore[arg-type]

    assert await _lines(adapter) == [f"prefix {REDACTED_MARKER} suffix"]


async def test_a_value_withheld_mid_stream_is_redacted_from_the_next_page() -> None:
    """A renewal installs a new GitHub token while the agent runs (#725)."""
    issued: list[str] = []
    printed = _printed(_CANARY)
    adapter, ops, _ = _stream([b"first\n", printed])
    original_observe = ops.observe

    async def renew_then_observe(
        ref: OperationRef, *, cursor: str | None, max_bytes: int, wait_seconds: float = 0
    ) -> ObservationPage:
        page = await original_observe(
            ref, cursor=cursor, max_bytes=max_bytes, wait_seconds=wait_seconds
        )
        issued.append(_CANARY)
        return page

    ops.observe = renew_then_observe  # type: ignore[method-assign]

    lines = [
        line async for line in adapter.stream(_HANDLE, ["claude"], withheld=lambda: tuple(issued))
    ]

    assert lines == ["first", f"prefix {REDACTED_MARKER} suffix"]


def _tool_lines_printing_the_canary() -> list[str]:
    """A Bash tool whose result prints the canary every way, as JSON the processor parses."""
    printed = " ".join(_LEAKED_FORMS.values())
    use = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t-leak",
                    "name": "Bash",
                    "input": {"command": f"echo {_CANARY}"},
                }
            ]
        },
    }
    result = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t-leak",
                    "content": f"{printed}\n{_CANARY}",
                    "is_error": False,
                }
            ]
        },
    }
    return [json.dumps(use), json.dumps(result)]


async def test_a_printed_credential_never_reaches_a_tool_event_or_a_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    blob = ("\n".join(_tool_lines_printing_the_canary()) + "\n").encode()
    cut = blob.index(_CANARY.encode()) + 5
    adapter, _, _ = _stream([blob[:cut], blob[cut:]])

    with caplog.at_level(logging.DEBUG):
        observations, _ = await _process(
            adapter.stream(_HANDLE, ["claude"], environment={"SYN_API_TOKEN": _CANARY})
        )

    kinds = [observation.kind for observation in observations]
    assert "tool_execution_started" in kinds, "the scrubbed lines are still valid JSON"
    assert "tool_execution_completed" in kinds
    recorded = "\n".join(observation.data_json for observation in observations)
    assert REDACTED_MARKER in recorded, "the tool event recorded the redaction, not nothing"
    _assert_no_form_of_the_canary(recorded)
    _assert_no_form_of_the_canary(caplog.text)


class TestResolveStreamExitCode:
    """The timeout decision itself (#969), carried over from the deleted
    ``test_stream_timeout_visibility.py`` when its ``docker exec`` transport
    tests went with the transport. The function is still the one ``status``
    resolution goes through, so its branches stay pinned here.
    """

    def test_timeout_with_a_success_status_becomes_the_timeout_code(self) -> None:
        assert (
            stream_adapter._resolve_stream_exit_code(0, timed_out=True)
            == stream_adapter._TIMEOUT_EXIT_CODE
        )

    def test_timeout_with_no_status_becomes_the_timeout_code(self) -> None:
        assert (
            stream_adapter._resolve_stream_exit_code(None, timed_out=True)
            == stream_adapter._TIMEOUT_EXIT_CODE
        )

    def test_a_clean_stream_is_never_rewritten(self) -> None:
        assert stream_adapter._resolve_stream_exit_code(0, timed_out=False) == 0

    def test_a_real_failure_status_survives_a_timeout(self) -> None:
        """A specific status beats a generic 'timed out' - the operator needs it."""
        assert stream_adapter._resolve_stream_exit_code(137, timed_out=True) == 137

    def test_an_interrupt_status_is_left_alone(self) -> None:
        """130 must reach the cancel path untouched, timed out or not."""
        assert stream_adapter._resolve_stream_exit_code(130, timed_out=False) == 130
        assert stream_adapter._resolve_stream_exit_code(130, timed_out=True) == 130
