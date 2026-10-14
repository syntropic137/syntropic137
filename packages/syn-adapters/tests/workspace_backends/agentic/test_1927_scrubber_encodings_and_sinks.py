"""#1927: every encoding, sink and setup path verification probed (synthetic values only)."""

import base64
import json
import logging

import pytest
from test_stream_on_operations import (
    _CANARY,
    _HANDLE,
    _LEAKED_FORMS,
    RecordingOperations,
    _Host,
    _lines,
    _process,
    _stream,
)

from syn_adapters.workspace_backends.agentic.credential_scrubber import (
    REDACTED_MARKER,
    CredentialScrubber,
)
from syn_adapters.workspace_backends.agentic.credentials import WorkspaceCredentials
from syn_adapters.workspace_backends.agentic.session_store_env import (
    session_store_credential_bindings,
)
from syn_adapters.workspace_backends.agentic.stream_adapter import AgenticEventStreamAdapter
from syn_shared.settings.session_store import SessionStoreSettings

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("encoding", sorted(_LEAKED_FORMS))
async def test_processor_logs_each_printed_encoding_are_scrubbed(encoding, caplog):
    form = _LEAKED_FORMS[encoding]
    printed = ("prefix " + form + " suffix\n").encode()
    cut = 7 + len(form) // 2
    adapter, _, _ = _stream([printed[:cut], printed[cut:]])
    with caplog.at_level(logging.DEBUG):
        await _process(adapter.stream(_HANDLE, ["claude"], environment={"SYN_API_TOKEN": _CANARY}))
    assert form not in caplog.text, encoding
    assert REDACTED_MARKER in caplog.text


async def test_withheld_github_value_is_absent_from_start_log(caplog):
    adapter, _, _ = _stream([(_CANARY + "\n").encode()])
    with caplog.at_level(logging.DEBUG):
        lines = [
            line
            async for line in adapter.stream(
                _HANDLE, ["sh", "-c", "echo " + _CANARY], withheld=lambda: (_CANARY,)
            )
        ]
    assert lines == [REDACTED_MARKER]
    assert _CANARY not in caplog.text


async def test_bound_value_is_absent_from_signal_diagnostic(caplog):
    adapter, _, _ = _stream([(_CANARY + "\n").encode()], exit_code=139)
    with caplog.at_level(logging.DEBUG):
        lines = [
            line
            async for line in adapter.stream(
                _HANDLE, ["sh", "-c", "echo " + _CANARY], environment={"SYN_API_TOKEN": _CANARY}
            )
        ]
    assert lines == [REDACTED_MARKER]
    assert _CANARY not in caplog.text
    assert _CANARY not in adapter.last_signal_death.describe()


@pytest.mark.parametrize("secret", ["ghs_CANARY/0b6f2c+Zq9X", "short7"])
async def test_entire_base64_value_becomes_fixed_marker(secret):
    encoded = base64.b64encode(secret.encode()).decode()
    adapter, _, _ = _stream([(encoded + "\n").encode()])
    assert await _lines(adapter, environment={"SYN_API_TOKEN": secret}) == [REDACTED_MARKER]


def test_base64_near_miss_is_untouched():
    secret = "ghs_CANARY/0b6f2c+Zq9X"
    near = secret[:-1] + "Y"
    encoded = base64.b64encode(near.encode()).decode()
    assert CredentialScrubber([secret]).scrub(encoded) == encoded


async def test_lowercase_url_encoding_is_redacted():
    encoded = _CANARY.replace("/", "%2f").replace("+", "%2b")
    adapter, _, _ = _stream([(encoded + "\n").encode()])
    assert await _lines(adapter, environment={"SYN_API_TOKEN": _CANARY}) == [REDACTED_MARKER]


async def test_json_serialized_secret_with_backslash_keeps_json_valid():
    secret = "abcdefgh" + chr(92)
    line = json.dumps({"content": secret}, ensure_ascii=False)
    adapter, _, _ = _stream([(line + "\n").encode()])
    out = await _lines(adapter, environment={"SYN_API_TOKEN": secret})
    assert json.loads(out[0])["content"] == REDACTED_MARKER


async def test_bound_raw_short_value_is_redacted():
    secret = "short7"
    settings = SessionStoreSettings(_env_file=None, url="https://store.invalid", auth_token=secret)
    credentials = WorkspaceCredentials(settings)
    (binding,) = session_store_credential_bindings(settings)
    resolved = await credentials.resolve(binding.ref)
    assert resolved == secret
    operations = RecordingOperations(credentials, [(resolved + "\n").encode()])
    adapter = AgenticEventStreamAdapter(_Host(operations, credentials))
    assert await _lines(adapter) == [REDACTED_MARKER]


@pytest.mark.parametrize("cut", range(1, len(_CANARY.encode())))
async def test_every_raw_byte_split_and_unterminated_end(cut):
    raw = _CANARY.encode()
    adapter, _, _ = _stream([raw[:cut], raw[cut:]])
    assert await _lines(adapter, environment={"SYN_API_TOKEN": _CANARY}) == [REDACTED_MARKER]


async def test_standard_wrapped_base64_of_long_model_key_is_redacted():
    secret = "sk-ant-api03_" + "0123456789abcdef" * 6
    encoded = base64.encodebytes(secret.encode())
    adapter, _, _ = _stream([encoded[:33], encoded[33:]])
    lines = await _lines(adapter, environment={"ANTHROPIC_API_KEY": secret})
    assert REDACTED_MARKER in "\n".join(lines), "standard 76-column base64 escaped unchanged"


async def test_real_setup_file_injection_feeds_codex_values_to_stream():
    from unittest.mock import AsyncMock, MagicMock

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_adapters.workspace_backends.service.setup_phase import run_setup_phase
    from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

    # Exercise the production injection path. The isolation double stores only
    # bytes actually handed to inject_files, then echoes that stored file on
    # the provider stream. This is a constructed response, not a recording.
    injected = {}
    adapter, ops, _ = _stream([b"empty\n"])

    async def inject(_handle, files, **kwargs):
        injected.update(files)

    async def execute(_handle, command, **kwargs):
        joined = " ".join(command)
        stdout = "STAGED_CREDENTIAL_ABSENT" if "STAGED_CREDENTIAL" in joined else ""
        return ExecutionResult(exit_code=0, success=True, duration_ms=1, stdout=stdout, stderr="")

    isolation = MagicMock()
    isolation.copy_to = AsyncMock(side_effect=inject)
    isolation.execute = AsyncMock(side_effect=execute)
    service = MagicMock()
    service._isolation = isolation
    service._event_stream = adapter
    workspace = ManagedWorkspace("ws-codex", "exec-codex", MagicMock(), _HANDLE, None, service)
    auth = json.dumps({"OPENAI_API_KEY": _CANARY})
    await run_setup_phase(workspace, SetupPhaseSecrets.for_testing(codex_auth_json=auth))
    assert injected[".setup/codex-auth.json"] == auth.encode()
    ops._pages = [injected[".setup/codex-auth.json"] + b"\n"]
    lines = [line async for line in workspace.stream(["codex", "exec"])]
    assert _CANARY not in "\n".join(lines)


async def test_numeric_bound_token_does_not_corrupt_jsonl():
    secret = "12345678"
    settings = SessionStoreSettings(_env_file=None, url="https://store.invalid", auth_token=secret)
    credentials = WorkspaceCredentials(settings)
    (binding,) = session_store_credential_bindings(settings)
    resolved = await credentials.resolve(binding.ref)
    assert resolved == secret
    line = json.dumps({"type": "result", "num_turns": 12345678, "result": resolved})
    operations = RecordingOperations(credentials, [(line + "\n").encode()])
    adapter = AgenticEventStreamAdapter(_Host(operations, credentials))
    lines = await _lines(adapter)
    parsed = json.loads(lines[0])
    assert parsed["result"] == REDACTED_MARKER


async def test_stdout_recovered_artifact_contains_only_scrubbed_values():
    from test_stream_on_operations import _LEAKED_FORMS, _Observations, _Workspace

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

    said = (
        "The workload printed its credential in raw, base64 and URL forms; the captured report must retain fixed redaction markers for each value. Captured output: "
        + " ".join(_LEAKED_FORMS.values())
    )
    event = json.dumps({"type": "result", "result": said})
    adapter, _, _ = _stream([(event + "\n").encode()])
    processor = EventStreamProcessor(
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        observability=_Observations(),
        controller=None,
        execution_id="exec-1927",
        phase_id="verify",
        session_id="s-1927",
        workspace_id="ws-1927",
        agent_model="claude-sonnet",
    )
    result = await processor.process_stream(
        adapter.stream(_HANDLE, ["claude"], environment={"SYN_API_TOKEN": _CANARY}), _Workspace()
    )
    repo = _Repo()
    await _collect(
        repo, [("artifacts/output/report.md", b"")], last_agent_message=result.last_agent_message
    )
    artifacts = _stored(repo)
    assert len(artifacts) == 1
    content = artifacts[0][1]
    assert content.count(REDACTED_MARKER) == len(_LEAKED_FORMS)
    for encoding, form in _LEAKED_FORMS.items():
        assert form not in content, encoding


@pytest.mark.parametrize(
    "secret", ["ghs_CANARY/0b6f2c+Zq9", "ghs_CANARY/0b6f2c+Zq9X", "ghs_CANARY/0b6f2c+Zq9XY"]
)
def test_padded_base64_at_every_length_remainder_is_the_marker(secret):
    assert len(secret) % 3 in (0, 1, 2)
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        encoded = encode(secret.encode()).decode()
        scrubber = CredentialScrubber([secret])
        assert scrubber.scrub(encoded) == REDACTED_MARKER, (secret, encoded)
        assert scrubber.scrub(encoded.rstrip("=")) == REDACTED_MARKER, (secret, encoded)


@pytest.mark.parametrize(
    "secret", ["ghs_CANARY/0b6f2c+Zq9", "ghs_CANARY/0b6f2c+Zq9X", "ghs_CANARY/0b6f2c+Zq9XY"]
)
def test_every_encoded_near_miss_is_untouched(secret):
    from urllib.parse import quote

    near = secret[:-1] + chr(ord(secret[-1]) + 1)
    scrubber = CredentialScrubber([secret])
    for form in (
        near,
        quote(near, safe=""),
        base64.b64encode(near.encode()).decode(),
        json.dumps({"content": near}),
    ):
        assert scrubber.scrub(form) == form


@pytest.mark.parametrize("width", [64, 76])
def test_base64_wrapped_inside_one_json_line_is_redacted(width):
    secret = "sk-ant-api03_" + "0123456789abcdef" * 6
    encoded = base64.b64encode(secret.encode()).decode()
    wrapped = "\n".join(encoded[i : i + width] for i in range(0, len(encoded), width))
    line = json.dumps({"type": "user", "content": wrapped})
    out = CredentialScrubber([secret]).scrub(line)
    assert json.loads(out)["content"] == REDACTED_MARKER
    for i in range(0, len(encoded), width):
        assert encoded[i : i + width] not in out


async def test_real_setup_file_injection_withholds_codex_token_auth():
    from unittest.mock import AsyncMock, MagicMock

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_adapters.workspace_backends.service.setup_phase import run_setup_phase
    from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

    access, refresh = "eyJhbGciOi.CANARY-access.sig0123", "rt_CANARY_refresh_0123456789"
    adapter, ops, _ = _stream([b"empty\n"])
    isolation = MagicMock()

    async def execute(_handle, command, **kwargs):
        joined = " ".join(command)
        stdout = "STAGED_CREDENTIAL_ABSENT" if "STAGED_CREDENTIAL" in joined else ""
        return ExecutionResult(exit_code=0, success=True, duration_ms=1, stdout=stdout, stderr="")

    isolation.copy_to = AsyncMock()
    isolation.execute = AsyncMock(side_effect=execute)
    service = MagicMock()
    service._isolation = isolation
    service._event_stream = adapter
    workspace = ManagedWorkspace("ws-codex", "exec-codex", MagicMock(), _HANDLE, None, service)
    auth = json.dumps(
        {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {"access_token": access, "refresh_token": refresh},
        }
    )
    await run_setup_phase(workspace, SetupPhaseSecrets.for_testing(codex_auth_json=auth))
    event = json.dumps({"type": "user", "content": auth})
    ops._pages = [(event + "\n").encode(), b"auth_mode chatgpt\n"]
    lines = [line async for line in workspace.stream(["codex", "exec"])]
    joined = "\n".join(lines)
    assert access not in joined and refresh not in joined
    assert json.loads(lines[0])["content"].count(REDACTED_MARKER) == 2
    assert lines[1] == "auth_mode chatgpt"
