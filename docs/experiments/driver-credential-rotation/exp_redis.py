"""Q3/Q4 for redis-py asyncio: is credential_provider re-invoked per connection?

Runs against a REAL redis-server with `requirepass`. Server-side facts come
from CLIENT LIST / CLIENT ID on an admin connection and from the server's own
WRONGPASS rejections - never from what the client believed it sent.

Mirrors the real call site: redis.asyncio.Redis.from_url(...), as used by
packages/syn-adapters/src/syn_adapters/redis_client.py:27.

Usage: python exp_redis.py <url> <admin-password>
"""

import asyncio
import pathlib
import sys

from redis.asyncio import Redis
from redis.credentials import CredentialProvider
from redis.exceptions import AuthenticationError, ResponseError

PW_FILE = pathlib.Path.home() / "exp" / "redispassword"


def out(label: str, value: object) -> None:
    print(f"{label:<42} {value}")


class FileCredentialProvider(CredentialProvider):
    """The credential provider under test: reads the file on every call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_credentials(self) -> tuple[str]:
        pw = PW_FILE.read_text().strip()
        self.calls.append(pw)
        return (pw,)

    async def get_credentials_async(self) -> tuple[str]:
        return self.get_credentials()


async def main(url: str, admin_pw: str) -> None:
    admin = Redis.from_url(url, password=admin_pw, decode_responses=True)
    await admin.config_set("requirepass", "rpw-v1")
    admin = Redis.from_url(url, password="rpw-v1", decode_responses=True)
    assert await admin.ping()
    PW_FILE.write_text("rpw-v1")

    cp = FileCredentialProvider()

    # --- Q3a: does from_url accept a credential_provider? ------------------
    client = Redis.from_url(
        url,
        credential_provider=cp,
        decode_responses=True,
        max_connections=10,
        client_name="exp-redis",
    )
    assert await client.ping()
    out("Q3a from_url(credential_provider=...)", "ACCEPTED (PING succeeded)")
    out("callable invocations after 1 conn", len(cp.calls))

    # --- Q3b: once per pool, or once per connection? -----------------------
    # Hold 5 pool connections open simultaneously, so 5 sockets must exist.
    pool = client.connection_pool
    held = [await pool.get_connection() for _ in range(5)]
    ids = []
    for conn in held:
        await conn.send_command("CLIENT", "ID")
        ids.append(await conn.read_response())
    server_side = [
        line
        for line in (await admin.client_list())
        if line.get("name") == "exp-redis"
    ]
    for conn in held:
        await pool.release(conn)

    out("server-side CLIENT ID values", sorted(ids))
    out("server-side CLIENT LIST name=exp-redis", len(server_side))
    out("callable invocations total", len(cp.calls))
    assert len(set(ids)) == 5, ids
    assert len(server_side) == 5, server_side
    # The initial PING's connection went back to the pool and was reused as
    # one of these five, so five sockets exist and five calls were made.
    assert len(cp.calls) == 5, cp.calls
    out("Q3b verdict", "ONCE PER SOCKET (5 sockets -> 5 calls)")

    # ...and a *reused* pooled connection does NOT re-invoke the provider:
    # the counter only moves when a new socket is opened.
    before = len(cp.calls)
    for _ in range(10):
        await client.ping()
    out("10 PINGs on pooled connections", f"{before} -> {len(cp.calls)} calls")
    assert len(cp.calls) == before, cp.calls

    # --- Q4: rotate with the process still running -------------------------
    await admin.config_set("requirepass", "rpw-v2")
    PW_FILE.write_text("rpw-v2")
    admin = Redis.from_url(url, password="rpw-v2", decode_responses=True)

    # Negative control: the server must now reject the old password.
    stale = Redis.from_url(url, password="rpw-v1", decode_responses=True)
    try:
        await stale.ping()
    except (AuthenticationError, ResponseError) as exc:
        out("old password, fresh connection", f"REJECTED by server: {exc}")
    else:
        raise AssertionError("old password still accepted - test is meaningless")
    await stale.aclose()

    # Same client object, same process, no restart. Drop the sockets so the
    # next command must open new ones.
    await pool.disconnect()
    cp.calls.clear()
    out("post-rotation PING", await client.ping())
    held = [await pool.get_connection() for _ in range(3)]
    new_ids = []
    for conn in held:
        await conn.send_command("CLIENT", "ID")
        new_ids.append(await conn.read_response())
    for conn in held:
        await pool.release(conn)
    out("post-rotation CLIENT ID values", sorted(new_ids))
    out("overlap with pre-rotation ids", sorted(set(ids) & set(new_ids)))
    out("post-rotation invocations", f"{len(cp.calls)} -> {sorted(set(cp.calls))}")
    assert not (set(ids) & set(new_ids)), "not actually new connections"
    assert cp.calls and set(cp.calls) == {"rpw-v2"}, cp.calls
    out("Q4 redis verdict", "YES - rotation picked up, no restart")

    # --- negative control: a static password cannot do this ----------------
    static = Redis.from_url(url, password="rpw-v2", decode_responses=True)
    assert await static.ping()
    await admin.config_set("requirepass", "rpw-v3")
    PW_FILE.write_text("rpw-v3")
    await static.connection_pool.disconnect()
    try:
        await static.ping()
    except (AuthenticationError, ResponseError) as exc:
        out("static-password client after rotation", f"BROKEN: {exc}")
    else:
        raise AssertionError("static client survived rotation - unexpected")
    await static.aclose()

    await pool.disconnect()
    out("callable client after 2nd rotation", await client.ping())

    await client.aclose()
    admin = Redis.from_url(url, password="rpw-v3", decode_responses=True)
    await admin.config_set("requirepass", "rpw-v1")
    await admin.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
