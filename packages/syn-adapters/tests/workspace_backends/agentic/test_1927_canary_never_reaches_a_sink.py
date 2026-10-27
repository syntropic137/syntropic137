"""An invented credential a workload prints never reaches a telemetry sink (#1927).

A real child process reads the canary from its environment and prints it raw,
base64-encoded on its own, base64-encoded inside a larger value, and
URL-encoded. Its bytes are paged through the stream adapter in 11-byte pages
and on into the real EventStreamProcessor, ArtifactCollector and the logs; no
sink may hold any of those forms. The provider transport is the in-process
double the other stream tests use, so this does not cover the provider's own
observation pages (agentic-workspace).

Each remaining test pins one shape an earlier suite left open: a renewal
issued after the first page, every chunk of wrapped base64, every item of a
JSON list, JSON keys, short values in an injected credential file, and a
nonempty file the agent captured its own output in, whether the canary was
issued, launch-only, or the session-store token only the adapter holds.
"""

import base64
import json
import logging
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import pytest
from agentic_isolation.config import WorkspaceConfig
from agentic_isolation.providers.base import Workspace as ProviderWorkspace
from agentic_isolation.providers.capabilities import TransferRoot
from agentic_isolation.providers.file_transfer import (
    DEFAULT_READ_LIMITS,
    ReadFilesResult,
    ReadLimits,
)
from agentic_isolation.providers.file_transfer import FileRefusal as AWRefusal
from test_stream_on_operations import _HANDLE, _Observations, _stream, _Workspace

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic.credential_scrubber import REDACTED_MARKER
from syn_adapters.workspace_backends.service.issued_tokens import IssuedToken
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase import run_setup_phase
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration._shared.file_transfer import FilesRefusedError
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
    IsolationHandle,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_empty_artifact_recovers_the_verdict import (
    _collect,
    _Repo,
    _stored,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_shared.settings.session_store import SessionStoreSettings

if TYPE_CHECKING:
    from agentic_isolation import AgenticWorkspace
    from agentic_isolation.providers.base import WorkspaceProvider

pytestmark = pytest.mark.unit

CANARY = "synpt_CANARY_1927_workload/0123456789+X"

_WORKLOAD = """
import base64, json, os, urllib.parse
s = os.environ["SYN_API_TOKEN"]
forms = [
    s,
    base64.b64encode(s.encode()).decode(),
    urllib.parse.quote(s, safe=""),
    base64.b64encode(("user:" + s + ":tail").encode()).decode(),
    base64.b64encode(("u:" + s).encode()).decode(),
    base64.urlsafe_b64encode(("us:" + s + "!").encode()).decode(),
]
for form in forms:
    print("printed: " + form)
said = "workload output: " + " ".join(forms)
print(json.dumps({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "env"}}]}}))
print(json.dumps({"type": "user", "message": {"content": [
    {"type": "tool_result", "tool_use_id": "a", "content": said, "is_error": False}]}}))
print(json.dumps({"type": "result", "result": said}))
"""

#: Every reversible form the workload prints. None may reach a sink.
_FORMS = (
    CANARY,
    base64.b64encode(CANARY.encode()).decode(),
    quote(CANARY, safe=""),
    base64.b64encode(f"user:{CANARY}:tail".encode()).decode(),
    base64.b64encode(f"u:{CANARY}".encode()).decode(),
    base64.urlsafe_b64encode(f"us:{CANARY}!".encode()).decode(),
)


def _workload_output() -> bytes:
    env = {**os.environ, "SYN_API_TOKEN": CANARY}
    return subprocess.run(
        [sys.executable, "-c", _WORKLOAD], env=env, check=True, capture_output=True
    ).stdout


def _leaks(sinks: dict[str, str]) -> list[str]:
    return [
        f"{sink} carries {form}" for sink, text in sinks.items() for form in _FORMS if form in text
    ]


async def test_a_printed_canary_reaches_no_sink_in_any_form(caplog: pytest.LogCaptureFixture):
    raw = _workload_output()
    assert all(form.encode() in raw for form in _FORMS), "the workload printed every form"
    adapter, _, _ = _stream([raw[i : i + 11] for i in range(0, len(raw), 11)])
    observations = _Observations()
    processor = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=observations,
        controller=None,
        execution_id="exec-1927",
        phase_id="verify",
        session_id="s",
        workspace_id="w",
        agent_model="claude-sonnet",
    )
    yielded: list[str] = []

    async def lines():
        environment = {"SYN_API_TOKEN": CANARY}
        async for line in adapter.stream(_HANDLE, ["workload"], environment=environment):
            yielded.append(line)
            yield line

    with caplog.at_level(logging.DEBUG):
        result = await processor.process_stream(lines(), _Workspace())
        repo = _Repo()
        await _collect(
            repo,
            [("artifacts/output/report.md", b"")],
            last_agent_message=result.last_agent_message,
        )

    kinds = {o.kind for o in observations.recorded}
    assert {"tool_execution_started", "tool_execution_completed"} <= kinds
    assert len(repo.saved) == 1
    sinks = {
        "yielded lines": "\n".join(yielded),
        "Lane 2 observations": "\n".join(o.data_json for o in observations.recorded),
        "stored artifact": str(_stored(repo)),
        "logs": caplog.text,
    }
    for sink, text in sinks.items():
        assert REDACTED_MARKER in text, f"{sink} carries no output at all"
    assert not _leaks(sinks), "\n".join(_leaks(sinks))


def _service(isolation: object, adapter: object = None) -> MagicMock:
    return MagicMock(_isolation=isolation, _event_stream=adapter or MagicMock())


def _workspace(adapter: object, isolation: MagicMock) -> ManagedWorkspace:
    return ManagedWorkspace(
        "ws-1927", "exec-1927", MagicMock(), _HANDLE, None, _service(isolation, adapter)
    )


def _setup_isolation(injected: dict[str, bytes]) -> MagicMock:
    async def inject(_handle: object, files: list[tuple[str, bytes]], **_kw: object) -> None:
        injected.update(files)

    async def execute(_handle: object, command: list[str], **_kw: object) -> ExecutionResult:
        staged = "STAGED_CREDENTIAL" in " ".join(command)
        stdout = "STAGED_CREDENTIAL_ABSENT" if staged else ""
        return ExecutionResult(exit_code=0, success=True, duration_ms=1, stdout=stdout, stderr="")

    return MagicMock(copy_to=AsyncMock(side_effect=inject), execute=AsyncMock(side_effect=execute))


@pytest.mark.parametrize("secret", [CANARY, "short7", "k"])
async def test_an_injected_file_value_is_withheld_however_short(secret: str):
    injected: dict[str, bytes] = {}
    adapter, ops, _ = _stream([b"empty\n"])
    workspace = _workspace(adapter, _setup_isolation(injected))
    auth = json.dumps({"OPENAI_API_KEY": secret})

    await run_setup_phase(workspace, SetupPhaseSecrets.for_testing(codex_auth_json=auth))

    # Print what was actually injected, not a value seeded by the test.
    value = json.loads(injected[".setup/codex-auth.json"])["OPENAI_API_KEY"]
    ops._pages = [f"{value}\n".encode()]
    assert [line async for line in workspace.stream(["workload"])] == [REDACTED_MARKER]


async def test_a_nonempty_captured_artifact_is_scrubbed_on_collection():
    """The agent tees its own output into a deliverable; the file is collected normally."""
    token = IssuedToken(CANARY, "inst-1", ("org/repo",), datetime.now(UTC) + timedelta(hours=1))
    captured = _workload_output()
    isolation = MagicMock(copy_from=AsyncMock(return_value=[("report.md", captured)]))
    workspace = _workspace(MagicMock(), isolation)
    workspace.issuance_ledger.record((token,))

    repo = _Repo()
    collector_files = await workspace.collect_files(patterns=["artifacts/output/**/*"])
    await _collect(repo, [(f"artifacts/output/{p}", c) for p, c in collector_files])

    assert len(repo.saved) == 1
    content = _stored(repo)[0][1]
    assert REDACTED_MARKER in content
    assert not _leaks({"stored artifact": content}), _leaks({"stored artifact": content})


async def _store(files: list[tuple[str, bytes]]) -> str:
    repo = _Repo()
    await _collect(repo, [(f"artifacts/output/{p}", c) for p, c in files])
    assert len(repo.saved) == 1
    return _stored(repo)[0][1]


@pytest.mark.parametrize("key", ["SYN_API_TOKEN", "OPENAI_API_KEY"])
async def test_a_launch_only_credential_is_scrubbed_from_collected_files(key: str):
    """The canary is in nothing but the launch environment: no ledger, no setup phase."""
    captured = _workload_output()
    adapter, _, _ = _stream([captured])
    isolation = MagicMock(copy_from=AsyncMock(return_value=[("report.md", captured)]))
    workspace = _workspace(adapter, isolation)

    lines = [line async for line in workspace.stream(["workload"], environment={key: CANARY})]
    assert not _leaks({"stream": "\n".join(lines)})

    content = await _store(await workspace.collect_files(patterns=["artifacts/output/**/*"]))
    assert REDACTED_MARKER in content
    assert "workload output: " in content, "useful output survives"
    assert not _leaks({"stored artifact": content}), _leaks({"stored artifact": content})


class _ReadsFiles:
    """A provider at the pinned `SupportsFileTransfer` boundary, holding ``files`` under /workspace."""

    name = "docker"

    def __init__(self, files: tuple[tuple[str, bytes], ...], refused: tuple[AWRefusal, ...] = ()):
        self.files = files
        self.refused = refused

    async def read_files(
        self,
        workspace: ProviderWorkspace,
        patterns: Sequence[str],
        *,
        base_path: TransferRoot,
        limits: ReadLimits = DEFAULT_READ_LIMITS,
    ) -> ReadFilesResult:
        return ReadFilesResult(files=self.files, refused=self.refused)


def _collecting(provider: _ReadsFiles) -> ManagedWorkspace:
    store = SessionStoreSettings(_env_file=None, auth_token=CANARY)  # type: ignore[arg-type]
    isolation = AgenticIsolationAdapter(
        session_store=store, provider=lambda _: cast("WorkspaceProvider", provider)
    )
    isolation._workspaces["ws-1927"] = cast(
        "AgenticWorkspace",
        ProviderWorkspace(
            id="ws-1927", provider="docker", path=Path("/workspace"), config=WorkspaceConfig()
        ),
    )
    handle = IsolationHandle(isolation_id="ws-1927", isolation_type="docker")
    return ManagedWorkspace("ws-1927", "exec-1927", MagicMock(), handle, None, _service(isolation))


async def test_the_session_store_token_is_scrubbed_from_collected_files():
    """Bound at create, never in a launch: only the isolation adapter knows it."""
    workspace = _collecting(_ReadsFiles((("artifacts/output/report.md", _workload_output()),)))

    files = await workspace.collect_files(patterns=["artifacts/output/**/*"])
    content = await _store([(Path(p).name, c) for p, c in files])
    assert REDACTED_MARKER in content
    assert "workload output: " in content, "useful output survives"
    assert not _leaks({"stored artifact": content}), _leaks({"stored artifact": content})


async def test_the_files_a_refusal_carries_are_scrubbed_too():
    """A refusal hands back what WAS read; those bytes leave through the same scrubber (#1913)."""
    workspace = _collecting(
        _ReadsFiles(
            (("artifacts/output/report.md", _workload_output()),),
            (AWRefusal("artifacts/output/link", "symlink"),),
        )
    )

    with pytest.raises(FilesRefusedError) as raised:
        await workspace.collect_files(patterns=["artifacts/output/**/*"])

    ((_, carried),) = raised.value.files
    content = await _store([("report.md", carried)])
    assert REDACTED_MARKER in content
    assert not _leaks({"stored artifact": content}), _leaks({"stored artifact": content})


async def test_a_renewal_issued_after_the_first_page_is_withheld_from_the_next():
    renewed = "ghs_RENEWED_1927_after_first_page_0123"
    issued = [CANARY]
    adapter, _, _ = _stream([f"{CANARY}\n".encode(), f"{renewed}\n".encode()])
    stream = adapter.stream(_HANDLE, ["workload"], withheld=lambda: tuple(issued))
    assert await stream.__anext__() == REDACTED_MARKER
    issued.append(renewed)  # only once the first page's scrubber is in use
    assert await stream.__anext__() == REDACTED_MARKER
    await stream.aclose()


@pytest.mark.parametrize("width", [64, 76])
async def test_every_wrapped_base64_chunk_is_redacted(width: int):
    secret = "sk-ant-CANARY_1927_" + "0123456789abcdef" * 6
    encoded = base64.b64encode(secret.encode()).decode()
    chunks = [encoded[i : i + width] for i in range(0, len(encoded), width)]
    adapter, _, _ = _stream([("\n".join(chunks) + "\n").encode()])
    environment = {"ANTHROPIC_API_KEY": secret}
    lines = [line async for line in adapter.stream(_HANDLE, ["w"], environment=environment)]
    assert len(chunks) > 1
    assert lines == [REDACTED_MARKER] * len(chunks)


async def test_every_json_list_item_key_and_replayed_line_is_scrubbed():
    second = "synpt_SECOND_1927_canary_0123456789"
    event = json.dumps(
        {
            CANARY: "public",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "missing", "content": value}
                    for value in (CANARY, second, f"nested {second} text")
                ]
            },
        }
    )
    raw = f"{event}\n{event}".encode()  # replayed, the last without a newline
    adapter, _, _ = _stream([raw[:9], raw[9:]])
    environment = {"SYN_API_TOKEN": CANARY, "OPENAI_API_KEY": second}
    lines = [line async for line in adapter.stream(_HANDLE, ["w"], environment=environment)]

    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert parsed[REDACTED_MARKER] == "public"
        assert CANARY not in parsed
        contents = [block["content"] for block in parsed["message"]["content"]]
        assert contents == [REDACTED_MARKER, REDACTED_MARKER, f"nested {REDACTED_MARKER} text"]
