"""Do the DECLARED floors (asyncpg>=0.30.0, redis>=5.0.0) have the mechanism?

The lockfile resolves to asyncpg 0.31.0 / redis 7.4.0, but the packages that
own the call sites only require the floors, so the floors are what a consumer
may actually get. Same real servers, same assertions, minimum viable subset.

Usage: python exp_floor_versions.py <pg-host> <pg-port> <redis-url>
"""

import asyncio
import sys

import asyncpg
import redis
from redis.asyncio import Redis
from redis.credentials import CredentialProvider


def out(label: str, value: object) -> None:
    print(f"{label:<44} {value}")


class Counting(CredentialProvider):
    def __init__(self, pw: str) -> None:
        self.pw = pw
        self.calls = 0

    def get_credentials(self) -> tuple[str]:
        self.calls += 1
        return (self.pw,)


async def main(host: str, port: int, redis_url: str) -> None:
    out("asyncpg version", asyncpg.__version__)
    out("redis version", redis.__version__)

    calls: list[str] = []

    def cb() -> str:
        calls.append("pw-v1")
        return "pw-v1"

    pool = await asyncpg.create_pool(
        host=host,
        port=port,
        user="rotuser",
        database="rotdb",
        password=cb,
        min_size=1,
        max_size=4,
        server_settings={"application_name": "exp-floor"},
    )
    held = [await pool.acquire() for _ in range(4)]
    pids = sorted({await c.fetchval("SELECT pg_backend_pid()") for c in held})
    for c in held:
        await pool.release(c)
    out("asyncpg backend PIDs / callable calls", f"{len(pids)} / {len(calls)}")
    assert len(pids) == 4 and len(calls) == 4, (pids, calls)
    await pool.close()

    cp = Counting("rpw-v1")
    client = Redis.from_url(
        redis_url, credential_provider=cp, decode_responses=True, client_name="exp-floor"
    )
    assert await client.ping()
    rpool = client.connection_pool
    conns = [await rpool.get_connection("PING") for _ in range(4)]
    ids = []
    for conn in conns:
        await conn.send_command("CLIENT", "ID")
        ids.append(await conn.read_response())
    for conn in conns:
        await rpool.release(conn)
    out("redis CLIENT IDs / provider calls", f"{len(set(ids))} / {cp.calls}")
    assert len(set(ids)) == 4 and cp.calls == 4, (ids, cp.calls)
    out("floor versions verdict", "mechanism present in BOTH floors")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3]))
