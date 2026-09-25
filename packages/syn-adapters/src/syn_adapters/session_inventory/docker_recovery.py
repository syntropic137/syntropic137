"""Reopen retained capture volumes in a verified, network-isolated helper."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import uuid4

from agentic_isolation.child_journal import WorkspaceChildJournalReader
from agentic_isolation.providers.base import ExecuteResult
from agentic_isolation.session_spool import WorkspaceSpoolReader, capture_retained_partition

from syn_adapters.workspace_backends.image_verification import verify_image_async

from .recovery_worker import RecoveryReaders
from .workspace_location import workspace_capture_location

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.agent_sessions import CaptureSpool


async def _read_limited(stream: asyncio.StreamReader, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await stream.read(65536):
        size += len(chunk)
        if size > limit:
            raise RuntimeError("Recovery command exceeded its output limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def _docker(
    args: list[str], *, timeout: float = 45, max_bytes: int = 34 * 1024 * 1024
) -> ExecuteResult:
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    try:
        async with asyncio.timeout(timeout):
            async with asyncio.TaskGroup() as group:
                stdout = group.create_task(_read_limited(process.stdout, max_bytes))
                stderr = group.create_task(_read_limited(process.stderr, 65536))
            code = await process.wait()
        return ExecuteResult(
            exit_code=code,
            stdout=stdout.result().decode(),
            stderr=stderr.result().decode(errors="replace"),
            duration_ms=0,
        )
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


class DockerSpoolRecovery:
    def __init__(self, image: str) -> None:
        self._image = image

    @asynccontextmanager
    async def open(self, spool: CaptureSpool) -> AsyncIterator[RecoveryReaders]:
        location = workspace_capture_location(spool.run, spool.session_id)
        # Never manufacture an empty replacement for a lost capture volume.
        exists = await _docker(["volume", "inspect", location.volume_name], max_bytes=65536)
        if exists.exit_code != 0:
            raise FileNotFoundError("Registered capture volume is not available")
        # Checked before our helper attaches: any other reference (a running or
        # stopped workspace) could still write, so this traversal cannot release.
        users = await _docker(
            ["ps", "-aq", "--no-trunc", "--filter", f"volume={location.volume_name}"],
            max_bytes=65536,
        )
        exclusive = users.exit_code == 0 and not users.stdout.strip()
        image = await verify_image_async(self._image)
        name = f"syn-capture-recovery-{uuid4().hex}"
        try:
            created = await _docker(
                [
                    "run",
                    "--rm",
                    "-d",
                    "--name",
                    name,
                    "--network=none",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--user=1000:1000",
                    "--memory=512m",
                    "--cpus=1",
                    "--pids-limit=64",
                    "--tmpfs=/tmp:rw,noexec,nosuid,size=32m,uid=1000,gid=1000",
                    "--mount",
                    f"type=volume,source={location.volume_name},target=/spool",
                    "--entrypoint=/usr/bin/timeout",
                    image,
                    "1800",
                    "/bin/sleep",
                    "infinity",
                ],
                max_bytes=65536,
            )
            if created.exit_code != 0:
                raise RuntimeError("Could not start capture recovery helper")

            async def execute(
                command: str,
                *,
                timeout: float | None = None,
                cwd: str | None = None,
                env: dict[str, str] | None = None,
            ) -> ExecuteResult:
                args = ["exec"]
                if cwd is not None:
                    args.extend(["-w", cwd])
                for key, value in (env or {}).items():
                    args.extend(["-e", f"{key}={value}"])
                return await _docker([*args, name, "/bin/sh", "-c", command], timeout=timeout or 30)

            await capture_retained_partition(execute, "/spool", location.partition)
            yield RecoveryReaders(
                transcripts=WorkspaceSpoolReader(execute, location.envelope_dir),
                children=WorkspaceChildJournalReader(
                    execute, f"/spool/.agentic-session-store/{location.partition}/children.sqlite"
                ),
                exclusive=exclusive,
            )
        finally:
            await _docker(["rm", "-f", name], timeout=15, max_bytes=65536)

    async def remove(self, spool: CaptureSpool) -> bool:
        """Remove a released capture volume. Docker refuses while any container uses it."""
        location = workspace_capture_location(spool.run, spool.session_id)
        result = await _docker(["volume", "rm", location.volume_name], max_bytes=65536)
        if result.exit_code == 0:
            return True
        detail = result.stderr.lower()
        if "no such volume" in detail:
            return True
        if "in use" in detail:
            return False
        # Never echo daemon output: it can carry host paths.
        raise RuntimeError("Capture volume removal failed")
