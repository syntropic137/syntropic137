"""Does the dynamic credential survive the shape the REAL call sites use?

Both call sites pass a DSN/URL that already carries the password:
  apps/syn-api/src/syn_api/_wiring_db.py:41   asyncpg.create_pool(str(db_url), ...)
  packages/syn-adapters/src/syn_adapters/redis_client.py:27
                                              Redis.from_url(url, ...)

So the question is not only "does a callable work" but "does it work when a
password is also present in the URL", and what a bare function does.

Usage: python exp_callsite_shapes.py <pg-dsn-with-stale-password> <redis-url>
"""

import asyncio
import sys

import asyncpg
from redis.asyncio import Redis
from redis.credentials import CredentialProvider
from redis.exceptions import DataError


def out(label: str, value: object) -> None:
    print(f"{label:<46} {value}")


class Provider(CredentialProvider):
    def __init__(self, pw: str) -> None:
        self.pw = pw

    def get_credentials(self) -> tuple[str]:
        return (self.pw,)

    async def get_credentials_async(self) -> tuple[str]:
        return (self.pw,)


async def main(pg_dsn_stale: str, redis_url: str) -> None:
    # --- asyncpg: DSN carries a WRONG password, callable carries the right one
    pool = await asyncpg.create_pool(pg_dsn_stale, password=lambda: "pw-v1", min_size=1, max_size=1)
    async with pool.acquire() as con:
        out("asyncpg: callable overrides DSN password", await con.fetchval("SELECT current_user"))
    await pool.close()

    # ...and confirm the DSN password really was the wrong one.
    try:
        await asyncpg.connect(pg_dsn_stale)
    except asyncpg.InvalidPasswordError as exc:
        out("asyncpg: DSN password alone", f"REJECTED: {exc}")
    else:
        raise AssertionError("stale DSN password was accepted")

    # --- redis: URL carries a password AND a credential_provider is passed.
    # from_url() itself is lazy - the pool only builds a Connection when a
    # command needs one, so the conflict surfaces on first use, not at
    # construction.
    both = Redis.from_url(
        redis_url.replace("redis://", "redis://:rpw-v1@"),
        credential_provider=Provider("rpw-v1"),
    )
    out("redis: from_url(url+password, provider)", "constructed without error")
    try:
        await both.ping()
    except DataError as exc:
        out("redis: first command with both", f"REJECTED: {exc.args[0].splitlines()[0]}")
    else:
        raise AssertionError("redis accepted both - expected DataError")
    await both.aclose()

    # --- redis: a bare callable is not a credential provider
    client = Redis.from_url(redis_url, credential_provider=lambda: ("rpw-v1",))
    try:
        await client.ping()
    except AttributeError as exc:
        out("redis: bare callable as provider", f"TypeError-ish: {exc}")
    else:
        raise AssertionError("bare callable worked - unexpected")
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
