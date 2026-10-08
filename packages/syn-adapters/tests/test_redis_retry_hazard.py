"""Redis adapters under the client's retry: applied, reply lost, resent (#1756).

``resilient_redis_client`` resends a command whose reply did not arrive. Redis
may already have applied it, so every adapter command must be harmless to run
twice. These tests put the real client (its own retry policy) in front of a
fake RESP server that applies a command and then loses the reply, by timing
out or by dropping the connection, and check what the adapter's caller sees.

The fake runs the signal claim script as a Python mirror of
``_CLAIM_SCRIPT`` (there is no Lua interpreter here), so these tests pin the
protocol the adapter relies on, not the Lua itself: a broken script passes
them. ``test_redis_retry_hazard_integration.py`` runs the real script on a real
Redis. The mirror is pinned to the script's SHA1: change the script and the
fake refuses to load it until the mirror and the pin are updated together.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import pytest

from syn_adapters.control.adapters.redis_adapter import RedisSignalQueueAdapter
from syn_adapters.control.commands import ControlSignal, ControlSignalType
from syn_adapters.dedup.redis_dedup import RedisDedupAdapter
from syn_adapters.redis_client import resilient_redis_client

if TYPE_CHECKING:
    from redis.asyncio import Redis

pytestmark = pytest.mark.unit

LossMode = Literal["timeout", "disconnect"]
Store = dict[bytes, bytes]
ScriptImpl = Callable[[Store, list[bytes], list[bytes]], bytes | None]

_CLIENT_TIMEOUT = 0.2

# SHA1 of the ``_CLAIM_SCRIPT`` that ``_mirror_claim_script`` mirrors.
_MIRRORED_SCRIPT_SHA1 = "70c6649b09a99ec7e123226c7e5b50567032d323"


def _mirror_claim_script(store: Store, keys: list[bytes], _args: list[bytes]) -> bytes | None:
    """Python mirror of ``redis_adapter._CLAIM_SCRIPT``."""
    signal_key, claim_key = keys
    if claim_key in store:
        return store[claim_key]
    signal = store.pop(signal_key, None)
    if signal is not None:
        store[claim_key] = signal
    return signal


@dataclass
class FakeRedis:
    """A RESP2 server that can apply a command and then lose its reply.

    ``lose_reply_once``: command names whose first successful application has
    its reply lost (``mode`` says how); with ``refuse_resends`` every later
    send of it is refused too. ``refuse``: command names the server never
    applies, dropping the connection instead.
    """

    mode: LossMode = "disconnect"
    lose_reply_once: set[str] = field(default_factory=set)
    refuse: set[str] = field(default_factory=set)
    refuse_resends: bool = False
    store: Store = field(default_factory=dict)
    applied: list[str] = field(default_factory=list)
    scripts: dict[str, ScriptImpl] = field(
        default_factory=lambda: {_MIRRORED_SCRIPT_SHA1: _mirror_claim_script}
    )
    _loaded: dict[str, ScriptImpl] = field(default_factory=dict)

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                argv = await _read_command(reader)
                if argv is None:
                    return
                name = argv[0].decode().upper()
                if name in self.refuse:
                    return
                reply = self._apply(name, argv[1:])
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
            writer.close()

    def _apply(self, name: str, args: list[bytes]) -> bytes:
        if name == "SET":
            key, value, *opts = args
            flags = [o.upper() for o in opts]
            if b"NX" in flags and key in self.store:
                self.applied.append(name)
                return b"$-1\r\n"
            self.store[key] = value
            self.applied.append(name)
            return b"+OK\r\n"
        if name == "GET":
            return _bulk(self.store.get(args[0]))
        if name == "GETDEL":
            self.applied.append(name)
            return _bulk(self.store.pop(args[0], None))
        if name == "DEL":
            self.applied.append(name)
            return b":%d\r\n" % sum(self.store.pop(k, None) is not None for k in args)
        if name == "SCRIPT" and args[0].upper() == b"LOAD":
            sha = hashlib.sha1(args[1]).hexdigest()
            if sha not in self.scripts:
                return b"-ERR no mirror for this script; update the mirror and its pin\r\n"
            self._loaded[sha] = self.scripts[sha]
            return _bulk(sha.encode())
        if name == "EVALSHA":
            impl = self._loaded.get(args[0].decode())
            if impl is None:
                return b"-NOSCRIPT No matching script.\r\n"
            numkeys = int(args[1])
            self.applied.append(name)
            return _bulk(impl(self.store, args[2 : 2 + numkeys], args[2 + numkeys :]))
        return b"+OK\r\n"  # CLIENT SETINFO and friends on connect


def _bulk(value: bytes | None) -> bytes:
    return b"$-1\r\n" if value is None else b"$%d\r\n%s\r\n" % (len(value), value)


async def _read_command(reader: asyncio.StreamReader) -> list[bytes] | None:
    header = await reader.readline()
    if not header:
        return None
    argv: list[bytes] = []
    for _ in range(int(header[1:])):
        length = int((await reader.readline())[1:])
        argv.append((await reader.readexactly(length + 2))[:-2])
    return argv


@pytest.fixture
async def fake() -> AsyncIterator[tuple[FakeRedis, Redis]]:
    server_state = FakeRedis()
    server = await asyncio.start_server(server_state.serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = resilient_redis_client(f"redis://127.0.0.1:{port}")
    # The production retry policy, a test-sized timeout: connections are
    # built lazily from these kwargs, so the change reaches every one.
    client.connection_pool.connection_kwargs["socket_timeout"] = _CLIENT_TIMEOUT
    yield server_state, client
    await client.aclose()
    server.close()
    await server.wait_closed()


def _cancel(execution_id: str) -> ControlSignal:
    return ControlSignal(
        signal_type=ControlSignalType.CANCEL, execution_id=execution_id, reason="stop"
    )


@pytest.mark.parametrize("mode", ["timeout", "disconnect"])
async def test_first_seen_event_survives_a_lost_set_nx_reply(
    fake: tuple[FakeRedis, Redis], mode: LossMode
) -> None:
    server, client = fake
    server.mode = mode
    server.lose_reply_once = {"SET"}
    dedup = RedisDedupAdapter(client)

    assert await dedup.is_duplicate("delivery-1") is False
    assert server.applied.count("SET") == 2, "the hazard did not fire: SET was not resent"
    assert await dedup.is_duplicate("delivery-1") is True


@pytest.mark.parametrize("mode", ["timeout", "disconnect"])
async def test_signal_survives_a_lost_claim_reply(
    fake: tuple[FakeRedis, Redis], mode: LossMode
) -> None:
    server, client = fake
    signals = RedisSignalQueueAdapter(client)
    await signals.enqueue("exec-1", _cancel("exec-1"))
    server.mode = mode
    server.lose_reply_once = {"EVALSHA"}

    received = await signals.dequeue("exec-1")

    assert server.applied.count("EVALSHA") == 2, "the hazard did not fire: claim was not resent"
    assert received == _cancel("exec-1")
    assert await signals.dequeue("exec-1") is None, "an acknowledged signal was delivered again"


async def test_signal_whose_claim_exhausts_retries_is_delivered_next_time(
    fake: tuple[FakeRedis, Redis],
) -> None:
    server, client = fake
    signals = RedisSignalQueueAdapter(client)
    await signals.enqueue("exec-2", _cancel("exec-2"))

    # Applied once, reply lost, and every resend refused: the call fails open.
    server.lose_reply_once = {"EVALSHA"}
    server.refuse_resends = True
    assert await signals.dequeue("exec-2") is None

    server.refuse = set()
    assert await signals.dequeue("exec-2") == _cancel("exec-2")


async def test_unacknowledged_signal_is_delivered_again(fake: tuple[FakeRedis, Redis]) -> None:
    server, client = fake
    signals = RedisSignalQueueAdapter(client)
    await signals.enqueue("exec-3", _cancel("exec-3"))
    server.refuse = {"DEL"}

    assert await signals.dequeue("exec-3") == _cancel("exec-3")

    server.refuse = set()
    assert await signals.dequeue("exec-3") == _cancel("exec-3")
    assert await signals.dequeue("exec-3") is None
