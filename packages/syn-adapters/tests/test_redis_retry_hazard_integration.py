"""The production claim script under the client's retry, on a real Redis (#1756).

``test_redis_retry_hazard.py`` drives the adapters against a fake server that
runs a Python mirror of ``_CLAIM_SCRIPT``, so it cannot see a broken script.
These tests run the exact Lua the adapter registers, on a real Redis, behind a
proxy that lets Redis apply a command and then loses the reply - by timing out
or by dropping the connection - so the production client resends it.

Run with: uv run pytest -m integration packages/syn-adapters/tests/test_redis_retry_hazard_integration.py

Redis comes from ``SYN_TEST_REDIS_URL`` when it is set (a scratch database:
it is flushed), otherwise from testcontainers, which needs Docker.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

import pytest

from syn_adapters.control.adapters.redis_adapter import RedisSignalQueueAdapter
from syn_adapters.control.commands import ControlSignal, ControlSignalType
from syn_adapters.dedup.redis_dedup import RedisDedupAdapter
from syn_adapters.redis_client import resilient_redis_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from redis.asyncio import Redis

pytestmark = pytest.mark.integration

LossMode = Literal["timeout", "disconnect"]

_CLIENT_TIMEOUT = 0.2


@dataclass
class LossyProxy:
    """Forwards each command to Redis; can lose the reply of one it applied.

    ``lose_reply_once``: command names whose next reply from Redis is dropped
    after Redis has applied the command (``mode`` says how); with
    ``refuse_resends`` every later send of it is refused, not forwarded.
    ``sent``: names of every command Redis actually received.
    """

    upstream_host: str
    upstream_port: int
    mode: LossMode = "disconnect"
    lose_reply_once: set[str] = field(default_factory=set)
    refuse: set[str] = field(default_factory=set)
    refuse_resends: bool = False
    sent: list[str] = field(default_factory=list)

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        up_reader, up_writer = await asyncio.open_connection(self.upstream_host, self.upstream_port)
        try:
            while True:
                raw = await _read_command(reader)
                if raw is None:
                    return
                frame, name = raw
                if name in self.refuse:
                    return
                up_writer.write(frame)
                await up_writer.drain()
                self.sent.append(name)
                reply = await _read_reply(up_reader)
                if name in self.lose_reply_once and not reply.startswith(b"-"):
                    self.lose_reply_once.discard(name)
                    if self.refuse_resends:
                        self.refuse.add(name)
                    if self.mode == "timeout":
                        await asyncio.sleep(_CLIENT_TIMEOUT * 3)
                    return
                writer.write(reply)
                await writer.drain()
        finally:
            up_writer.close()
            writer.close()


async def _read_command(reader: asyncio.StreamReader) -> tuple[bytes, str] | None:
    header = await reader.readline()
    if not header:
        return None
    frame = bytearray(header)
    name = ""
    for i in range(int(header[1:])):
        length_line = await reader.readline()
        body = await reader.readexactly(int(length_line[1:]) + 2)
        frame += length_line + body
        if i == 0:
            name = body[:-2].decode().upper()
    return bytes(frame), name


async def _read_reply(reader: asyncio.StreamReader) -> bytes:
    """One complete RESP2 reply, raw."""
    line = await reader.readline()
    kind, rest = line[:1], line[1:-2]
    if kind == b"$" and int(rest) >= 0:
        return line + await reader.readexactly(int(rest) + 2)
    if kind == b"*" and int(rest) > 0:
        parts = [line]
        for _ in range(int(rest)):
            parts.append(await _read_reply(reader))
        return b"".join(parts)
    return line


@pytest.fixture
def redis_url() -> Iterator[str]:
    url = os.environ.get("SYN_TEST_REDIS_URL")
    if url:
        yield url
        return
    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        yield f"redis://{host}:{container.get_exposed_port(6379)}"


@pytest.fixture
async def proxied(redis_url: str) -> AsyncIterator[tuple[LossyProxy, Redis]]:
    target = urlsplit(redis_url)
    proxy = LossyProxy(target.hostname or "127.0.0.1", target.port or 6379)
    server = await asyncio.start_server(proxy.serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    db = target.path or "/0"
    client = resilient_redis_client(f"redis://127.0.0.1:{port}{db}")
    # The production retry policy, a test-sized timeout: connections are
    # built lazily from these kwargs, so the change reaches every one.
    client.connection_pool.connection_kwargs["socket_timeout"] = _CLIENT_TIMEOUT
    await client.flushdb()
    proxy.sent.clear()
    yield proxy, client
    with contextlib.suppress(Exception):
        await client.flushdb()
    await client.aclose()
    server.close()
    await server.wait_closed()


def _cancel(execution_id: str) -> ControlSignal:
    return ControlSignal(
        signal_type=ControlSignalType.CANCEL, execution_id=execution_id, reason="stop"
    )


@pytest.mark.parametrize("mode", ["timeout", "disconnect"])
async def test_signal_survives_a_lost_claim_reply(
    proxied: tuple[LossyProxy, Redis], mode: LossMode
) -> None:
    proxy, client = proxied
    signals = RedisSignalQueueAdapter(client)
    await signals.enqueue("exec-1", _cancel("exec-1"))
    # Load the script first, so the lost reply is the claim's, not SCRIPT LOAD's.
    await signals.dequeue("exec-0")
    proxy.mode = mode
    proxy.lose_reply_once = {"EVALSHA"}
    before = proxy.sent.count("EVALSHA")

    received = await signals.dequeue("exec-1")

    assert proxy.sent.count("EVALSHA") - before == 2, "the hazard did not fire: claim not resent"
    assert received == _cancel("exec-1"), "the signal was lost to a retried claim"
    assert await signals.dequeue("exec-1") is None, "an acknowledged signal was delivered again"


async def test_signal_whose_claim_exhausts_retries_is_delivered_next_time(
    proxied: tuple[LossyProxy, Redis],
) -> None:
    proxy, client = proxied
    signals = RedisSignalQueueAdapter(client)
    await signals.enqueue("exec-2", _cancel("exec-2"))
    await signals.dequeue("exec-0")

    # Applied once, reply lost, and every resend refused: the call fails open.
    proxy.lose_reply_once = {"EVALSHA"}
    proxy.refuse_resends = True
    assert await signals.dequeue("exec-2") is None

    proxy.refuse = set()
    assert await signals.dequeue("exec-2") == _cancel("exec-2"), "the claimed signal was lost"


@pytest.mark.parametrize("mode", ["timeout", "disconnect"])
async def test_first_seen_event_survives_a_lost_set_nx_reply(
    proxied: tuple[LossyProxy, Redis], mode: LossMode
) -> None:
    proxy, client = proxied
    proxy.mode = mode
    proxy.lose_reply_once = {"SET"}
    dedup = RedisDedupAdapter(client)

    assert await dedup.is_duplicate("delivery-1") is False
    assert proxy.sent.count("SET") == 2, "the hazard did not fire: SET was not resent"
    assert await dedup.is_duplicate("delivery-1") is True
