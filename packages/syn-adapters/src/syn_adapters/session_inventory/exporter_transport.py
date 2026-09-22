"""Bounded subprocess seam to the standard exporter, never a second HTTP client."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

if TYPE_CHECKING:
    from pathlib import Path

    from apss_session_capture.inventory import InventoryOperation, QualifiedTranscript


class ExporterTransportError(RuntimeError):
    """A safe diagnostic that never includes subprocess output or credentials."""


@dataclass(frozen=True)
class ExporterConfig:
    binary: Path
    outbox_dir: Path
    store_url: str
    token: SecretStr
    timeout_seconds: float = 45

    def __post_init__(self) -> None:
        if not self.binary.is_absolute() or not self.outbox_dir.is_absolute():
            raise ValueError("exporter binary and outbox directory must be absolute")
        if self.timeout_seconds <= 0:
            raise ValueError("exporter timeout must be positive")


class EnqueueReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    schema_version: int = Field(strict=True, ge=1, le=1)
    inserted: bool


class ReplicationDrain(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    acknowledged: int = Field(ge=0)
    pending: int = Field(ge=0)
    failed: int = Field(ge=0)
    remaining: int = Field(ge=0)


class CaptureDrain(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    acknowledged: int = Field(ge=0)
    failed: int = Field(ge=0)
    remaining: int = Field(ge=0)


class ExporterCaptureReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    storage_key: str = Field(pattern=r"^qts1:[a-f0-9]{64}$")
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    stored_content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    duplicate: bool


class CaptureReceiptLookup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    schema_version: int = Field(strict=True, ge=1, le=1)
    receipt: ExporterCaptureReceipt | None


def _capture_payload(identity: QualifiedTranscript, envelope: bytes) -> bytes:
    prefix = b'{"identity":' + identity.model_dump_json().encode() + b',"envelope":'
    if len(prefix) + len(envelope) + 1 > 64 * 1024 * 1024:
        raise ExporterTransportError("capture exceeds exporter input limit")
    return prefix + envelope + b"}"


class ExporterCaptureTransport:
    """Deliver archived envelope bytes through the standard exporter's durable queue."""

    def __init__(self, config: ExporterConfig) -> None:
        self._config = config

    async def enqueue(self, identity: QualifiedTranscript, envelope: bytes) -> EnqueueReceipt:
        # The standard exporter parses/validates the original envelope. Do not
        # parse and reconstruct native content in this orchestration adapter.
        payload = _capture_payload(identity, envelope)
        code, output = await _run_exporter(
            self._config, ("--capture-enqueue",), payload, channel="capture"
        )
        if code != 0:
            raise ExporterTransportError("exporter rejected capture")
        try:
            return EnqueueReceipt.model_validate_json(output)
        except ValueError:
            raise ExporterTransportError("exporter returned an invalid capture receipt") from None

    async def receipt(
        self, identity: QualifiedTranscript, envelope: bytes
    ) -> ExporterCaptureReceipt | None:
        code, output = await _run_exporter(
            self._config,
            ("--capture-receipt",),
            _capture_payload(identity, envelope),
            channel="capture",
        )
        if code != 0:
            raise ExporterTransportError("exporter could not retrieve capture receipt")
        try:
            result = CaptureReceiptLookup.model_validate_json(output).receipt
        except ValueError:
            raise ExporterTransportError("exporter returned an invalid capture receipt") from None
        if result is not None and result.storage_key != identity.storage_key():
            raise ExporterTransportError("exporter receipt identifies another capture")
        return result

    async def drain(self, limit: int = 1) -> CaptureDrain:
        if not 1 <= limit <= 50:
            raise ValueError("capture drain limit must be 1..50")
        code, output = await _run_exporter(
            self._config, ("--capture-drain", str(limit)), b"", channel="capture"
        )
        if code not in (0, 3):
            raise ExporterTransportError("exporter could not drain captures")
        try:
            result = CaptureDrain.model_validate_json(output)
        except ValueError:
            raise ExporterTransportError(
                "exporter returned an invalid capture drain receipt"
            ) from None
        if (code == 0) != (result.remaining == 0) or result.acknowledged + result.failed > limit:
            raise ExporterTransportError("exporter capture drain contradicts its receipt")
        return result


async def _bounded_output(stream: asyncio.StreamReader | None) -> bytes:
    if stream is None:
        raise ExporterTransportError("exporter output pipe unavailable")
    try:
        await stream.readexactly(4097)
    except asyncio.IncompleteReadError as exc:
        return exc.partial
    raise ExporterTransportError("exporter output exceeded its limit")


async def _write_input(process: asyncio.subprocess.Process, payload: bytes) -> None:
    if process.stdin is None:
        raise ExporterTransportError("exporter input pipe unavailable")
    process.stdin.write(payload)
    await process.stdin.drain()
    process.stdin.close()
    await process.stdin.wait_closed()


class ExporterInventoryTransport:
    def __init__(self, config: ExporterConfig) -> None:
        self._config = config

    async def enqueue(self, operation: InventoryOperation) -> EnqueueReceipt:
        payload = operation.model_dump_json().encode()
        if len(payload) > 2 * 1024 * 1024:
            raise ExporterTransportError("inventory operation exceeds exporter input limit")
        code, output = await self._run(("--inventory-enqueue",), payload)
        if code != 0:
            raise ExporterTransportError("exporter rejected inventory operation")
        try:
            return EnqueueReceipt.model_validate_json(output)
        except ValueError:
            raise ExporterTransportError("exporter returned an invalid enqueue receipt") from None

    async def drain(self, limit: int = 1) -> ReplicationDrain:
        if not 1 <= limit <= 500:
            raise ValueError("drain limit must be 1..500")
        code, output = await self._run(("--inventory-drain", str(limit)), b"")
        if code not in (0, 3):
            raise ExporterTransportError("exporter could not drain inventory")
        try:
            result = ReplicationDrain.model_validate_json(output)
        except ValueError:
            raise ExporterTransportError("exporter returned an invalid drain receipt") from None
        if (code == 0) != (result.remaining == 0):
            raise ExporterTransportError("exporter drain status contradicts its receipt")
        if result.acknowledged + result.pending + result.failed > limit:
            raise ExporterTransportError("exporter drain receipt exceeds requested work")
        return result

    async def _run(self, arguments: tuple[str, ...], payload: bytes) -> tuple[int, bytes]:
        return await _run_exporter(self._config, arguments, payload, channel="inventory")


async def _run_exporter(
    config: ExporterConfig,
    arguments: tuple[str, ...],
    payload: bytes,
    *,
    channel: Literal["inventory", "capture"],
) -> tuple[int, bytes]:
    process: asyncio.subprocess.Process | None = None
    try:
        async with asyncio.timeout(config.timeout_seconds):
            process = await asyncio.create_subprocess_exec(
                str(config.binary),
                *arguments,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Deliberate process-environment mapping, not domain state.
                env={
                    "SESSION_STORE_URL": config.store_url,
                    (
                        "CAPTURE_WRITE_TOKEN" if channel == "capture" else "INVENTORY_WRITE_TOKEN"
                    ): config.token.get_secret_value(),
                    (
                        "EXPORTER_CAPTURE_DIR" if channel == "capture" else "EXPORTER_INVENTORY_DIR"
                    ): str(config.outbox_dir),
                    **(
                        {"SYSTEMROOT": os.environ["SYSTEMROOT"]}
                        if "SYSTEMROOT" in os.environ
                        else {}
                    ),
                },
            )
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(_write_input(process, payload))
                stdout = tasks.create_task(_bounded_output(process.stdout))
                tasks.create_task(_bounded_output(process.stderr))
                status = tasks.create_task(process.wait())
            return status.result(), stdout.result()
    except Exception:
        raise ExporterTransportError("exporter process failed or timed out") from None
    finally:
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
