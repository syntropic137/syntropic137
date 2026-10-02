"""Subprocess protocol limits and real exporter compatibility."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from apss_session_capture.inventory import (
    InventoryRevision,
    PublishOperation,
    QualifiedRun,
    QualifiedTranscript,
)
from pydantic import SecretStr

from syn_adapters.session_inventory.exporter_transport import (
    ExporterCaptureTransport,
    ExporterConfig,
    ExporterInventoryTransport,
    ExporterTransportError,
)


@pytest.mark.unit
async def test_capture_transport_preserves_bytes_and_separates_credentials(tmp_path: Path) -> None:
    script = tmp_path / "capture-exporter"
    script.write_text(
        f"#!{sys.executable}\n"
        + """import os,sys
payload=sys.stdin.buffer.read()
assert os.environ['CAPTURE_WRITE_TOKEN']=='capture-only'
assert 'INVENTORY_WRITE_TOKEN' not in os.environ
assert 'EXPORTER_CAPTURE_DIR' in os.environ
if sys.argv[1]=='--capture-enqueue':
    assert payload.endswith(b',"envelope":{ "raw" : "native" }}')
    print('{"schema_version":1,"inserted":true}')
else:
    print('{"acknowledged":0,"failed":1,"remaining":1}')
    sys.exit(3)
"""
    )
    script.chmod(0o700)
    transport = ExporterCaptureTransport(
        ExporterConfig(
            binary=script,
            outbox_dir=tmp_path / "queue",
            store_url="http://unused.invalid",
            token=SecretStr("capture-only"),
        )
    )
    identity = QualifiedTranscript(
        source_instance_id="source", harness="codex", native_session_id="native"
    )
    assert (await transport.enqueue(identity, b'{ "raw" : "native" }')).inserted
    result = await transport.drain()
    assert result.failed == 1 and result.remaining == 1
    with pytest.raises(ValueError, match=r"1\.\.50"):
        await transport.drain(51)


@pytest.mark.unit
@pytest.mark.parametrize(
    "reply",
    [
        '{"acknowledged":0,"failed":0,"remaining":1}',
        '{"acknowledged":2,"failed":0,"remaining":0}',
        '{"acknowledged":false,"failed":0,"remaining":0}',
        "not-json",
    ],
)
async def test_capture_transport_rejects_contradictory_receipts(tmp_path: Path, reply: str) -> None:
    script = tmp_path / "capture-exporter"
    script.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdin.buffer.read()\nprint({reply!r})\n"
    )
    script.chmod(0o700)
    transport = ExporterCaptureTransport(
        ExporterConfig(
            binary=script,
            outbox_dir=tmp_path / "queue",
            store_url="http://unused.invalid",
            token=SecretStr("capture-only"),
        )
    )
    with pytest.raises(ExporterTransportError):
        await transport.drain()


def operation() -> PublishOperation:
    return PublishOperation(
        operation="publish",
        body=InventoryRevision(
            run=QualifiedRun(source_instance_id="source", execution_id="run"),
            revision_id="revision",
            parent_revision_id=None,
            revision_sequence=1,
            producer_id="syntropic137-inventory",
            sequence_high_watermark=0,
            resolver_version="v1",
            coverage="unknown",
            expected_record_count=0,
        ),
    )


def fake(tmp_path: Path, source: str, timeout: float = 5) -> ExporterInventoryTransport:
    script = tmp_path / "exporter"
    script.write_text(f"#!{sys.executable}\nimport sys\nsys.stdin.buffer.read()\n{source}\n")
    script.chmod(0o700)
    return ExporterInventoryTransport(
        ExporterConfig(
            binary=script,
            outbox_dir=tmp_path / "outbox",
            store_url="http://unused.invalid",
            token=SecretStr("do-not-expose"),
            timeout_seconds=timeout,
        )
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        'print("do-not-expose", file=sys.stderr); sys.exit(1)',
        'print("x" * 4097)',
        'print("x" * 4097, file=sys.stderr)',
        'print("not-json")',
        'print(\'{"schema_version":2,"inserted":true}\')',
    ],
)
async def test_failed_or_malformed_receipts_are_safe_and_unacknowledged(
    tmp_path: Path, source: str
) -> None:
    transport = fake(tmp_path, source)
    with pytest.raises(ExporterTransportError) as caught:
        await transport.enqueue(operation())
    assert "do-not-expose" not in str(caught.value)


@pytest.mark.unit
async def test_timeout_terminates_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    transport = fake(
        tmp_path,
        f"import os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\ntime.sleep(30)",
        timeout=0.3,
    )
    with pytest.raises(ExporterTransportError):
        await transport.enqueue(operation())
    if pid_file.exists():
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)


@pytest.mark.unit
@pytest.mark.parametrize(
    "code,remaining,valid", [(0, 0, True), (3, 1, True), (0, 1, False), (3, 0, False)]
)
async def test_drain_exit_code_must_agree_with_pending_work(
    tmp_path: Path, code: int, remaining: int, valid: bool
) -> None:
    transport = fake(
        tmp_path,
        f'print(\'{{"acknowledged":1,"pending":0,"failed":0,"remaining":{remaining}}}\'); sys.exit({code})',
    )
    if valid:
        assert (await transport.drain()).remaining == remaining
    else:
        with pytest.raises(ExporterTransportError):
            await transport.drain()


@pytest.mark.integration
async def test_real_exporter_accepts_apss_python_messages_and_retains_failed_upload(
    tmp_path: Path,
) -> None:
    binary = os.environ.get("SYN_TEST_EXPORTER_BINARY")
    if binary is None:
        pytest.skip("SYN_TEST_EXPORTER_BINARY must point to the built standard exporter")
    config = ExporterConfig(
        binary=Path(binary),
        outbox_dir=tmp_path / "outbox",
        store_url="http://127.0.0.1:1",
        token=SecretStr("test-only-token"),
    )
    first = ExporterInventoryTransport(config)
    assert (await first.enqueue(operation())).inserted
    restarted = ExporterInventoryTransport(config)
    assert not (await restarted.enqueue(operation())).inserted
    result = await restarted.drain()
    assert result.failed == 1
    assert result.remaining == 1
    assert result.acknowledged == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "reply",
    [
        "not-json",
        '{"schema_version":1}',
        '{"schema_version":true,"receipt":null}',
        '{"schema_version":2,"receipt":null}',
        '{"schema_version":1,"receipt":null,"unexpected":true}',
        '{"schema_version":1,"receipt":{"storage_key":"qts1:'
        + "a" * 64
        + '","content_hash":"sha256:'
        + "b" * 64
        + '","stored_content_hash":"sha256:'
        + "c" * 64
        + '","duplicate":false}}',
    ],
)
async def test_capture_receipt_lookup_rejects_invalid_or_foreign_output(
    tmp_path: Path, reply: str
) -> None:
    script = tmp_path / "receipt-exporter"
    script.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdin.buffer.read()\n"
        f"assert sys.argv[1]=='--capture-receipt'\nprint({reply!r})\n"
    )
    script.chmod(0o700)
    transport = ExporterCaptureTransport(
        ExporterConfig(
            binary=script,
            outbox_dir=tmp_path / "queue",
            store_url="http://unused.invalid",
            token=SecretStr("private-token"),
        )
    )
    identity = QualifiedTranscript(
        source_instance_id="source", harness="codex", native_session_id="native"
    )
    with pytest.raises(ExporterTransportError) as caught:
        await transport.receipt(identity, b"{}")
    assert "private-token" not in str(caught.value)
    assert reply not in str(caught.value)
