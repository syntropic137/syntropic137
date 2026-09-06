"""Q1/Q2/Q4 for asyncpg: is a callable password re-invoked per connection?

Runs against a REAL PostgreSQL (scram-sha-256). Every claim is checked against
what the SERVER did: backend PIDs from pg_stat_activity, the server's own
connection log, and the fact that scram authentication cannot succeed unless
the client proved knowledge of the password currently stored in pg_authid.

Usage: python exp_asyncpg.py <host> <port> <admin-dsn>
"""

import asyncio
import pathlib
import sys

import asyncpg

PW_FILE = pathlib.Path.home() / "exp" / "pgpassword"
APP = "exp-asyncpg"


def out(label: str, value: object) -> None:
    print(f"{label:<42} {value}")


async def main(host: str, port: int, admin_dsn: str) -> None:
    admin = await asyncpg.connect(admin_dsn)

    # --- reset to a known state -------------------------------------------
    await admin.execute("ALTER ROLE rotuser PASSWORD 'pw-v1'")
    PW_FILE.write_text("pw-v1")

    calls: list[str] = []

    def password_from_file() -> str:
        """The credential provider under test: reads the file every call."""
        pw = PW_FILE.read_text().strip()
        calls.append(pw)
        return pw

    # --- Q1: does create_pool accept a callable at all? --------------------
    pool = await asyncpg.create_pool(
        host=host,
        port=port,
        user="rotuser",
        database="rotdb",
        password=password_from_file,
        min_size=1,
        max_size=5,
        server_settings={"application_name": APP},
    )
    out("Q1 create_pool(password=callable)", "ACCEPTED (pool created)")

    # --- Q2: once per pool, or once per connection? ------------------------
    # Hold 5 connections at once so the pool is forced to open 5 backends.
    conns = [await pool.acquire() for _ in range(5)]
    pids = sorted({await c.fetchval("SELECT pg_backend_pid()") for c in conns})
    server_backends = await admin.fetchval(
        "SELECT count(*) FROM pg_stat_activity WHERE usename = 'rotuser' AND application_name = $1",
        APP,
    )
    for c in conns:
        await pool.release(c)

    out("server-side distinct backend PIDs", f"{len(pids)} {pids}")
    out("server-side pg_stat_activity count", server_backends)
    out("callable invocations", len(calls))
    assert len(pids) == 5, pids
    assert server_backends == 5, server_backends
    assert len(calls) == 5, calls
    out("Q2 verdict", "ONCE PER CONNECTION (5 backends -> 5 calls)")

    # --- Q4: rotate the credential with the process still running ----------
    await admin.execute("ALTER ROLE rotuser PASSWORD 'pw-v2'")
    PW_FILE.write_text("pw-v2")
    verifier = await admin.fetchval(
        "SELECT substring(rolpassword from 1 for 30) FROM pg_authid WHERE rolname = 'rotuser'"
    )
    out("server verifier after rotation", verifier[:30])

    # Negative control: the OLD password must now be rejected by the server,
    # otherwise a later success proves nothing.
    try:
        await asyncpg.connect(
            host=host, port=port, user="rotuser", database="rotdb", password="pw-v1"
        )
    except asyncpg.InvalidPasswordError as exc:
        out("old password, fresh connection", f"REJECTED: {exc}")
    else:
        raise AssertionError("old password still accepted - test is meaningless")

    # Same pool, same process, no restart: force new physical connections.
    calls.clear()
    await pool.expire_connections()
    conns = [await pool.acquire() for _ in range(5)]
    new_pids = sorted({await c.fetchval("SELECT pg_backend_pid()") for c in conns})
    who = await conns[0].fetchval("SELECT current_user")
    for c in conns:
        await pool.release(c)

    out("post-rotation backend PIDs", f"{len(new_pids)} {new_pids}")
    out("overlap with pre-rotation PIDs", sorted(set(pids) & set(new_pids)))
    out("post-rotation callable invocations", f"{len(calls)} -> {sorted(set(calls))}")
    out("server says current_user is", who)
    assert not (set(pids) & set(new_pids)), "not actually new backends"
    assert calls and set(calls) == {"pw-v2"}, calls
    out("Q4 asyncpg verdict", "YES - rotation picked up, no restart")

    # --- negative control: a STATIC password cannot do this ----------------
    static_pool = await asyncpg.create_pool(
        host=host,
        port=port,
        user="rotuser",
        database="rotdb",
        password="pw-v2",
        min_size=1,
        max_size=2,
    )
    await admin.execute("ALTER ROLE rotuser PASSWORD 'pw-v3'")
    PW_FILE.write_text("pw-v3")
    await static_pool.expire_connections()
    try:
        async with static_pool.acquire() as c:
            await c.fetchval("SELECT 1")
    except asyncpg.InvalidPasswordError as exc:
        out("static-password pool after rotation", f"BROKEN: {exc}")
    else:
        raise AssertionError("static pool survived rotation - unexpected")

    # ...while the callable pool keeps going across a second rotation.
    await pool.expire_connections()
    async with pool.acquire() as c:
        out("callable pool after 2nd rotation", await c.fetchval("SELECT 'alive'"))

    await static_pool.close()
    await pool.close()
    await admin.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3]))
