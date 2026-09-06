# Driver credential-rotation experiment

Scripts backing [`../2026-09-06-driver-credential-rotation.md`](../2026-09-06-driver-credential-rotation.md).
They are standalone experiments, not part of the test suite, and they touch no
production code. They mutate the credentials of the server you point them at, so
point them at a throwaway one.

Each script takes its endpoints as arguments and asserts on server-side facts
(backend PIDs, `pg_stat_activity`, `CLIENT ID`/`CLIENT LIST`, the server's own
auth rejections) rather than on client-side belief.

| Script | Answers |
|---|---|
| `exp_asyncpg.py` | Q1, Q2, Q4 for asyncpg |
| `exp_redis.py` | Q3, Q4 for redis-py asyncio |
| `exp_callsite_shapes.py` | Whether a dynamic credential survives the argument shape this repo's real call sites use |
| `exp_floor_versions.py` | Whether the mechanism exists at the declared floors (`asyncpg==0.30.0`, `redis==5.0.0`) |

## Getting servers without Docker

The original run had no Docker (and no root), so both servers came from PyPI
wheels. `/tmp` is `noexec` in the agent image, so the venv must live elsewhere.

```bash
uv venv ~/srvvenv
uv pip install --python ~/srvvenv/bin/python pgserver redislite

# PostgreSQL 16.2
mkdir -p ~/exp/pgdata
~/srvvenv/bin/python -c "import pgserver; pgserver.get_server('$HOME/exp/pgdata', cleanup_mode=None)"
cat >> ~/exp/pgdata/postgresql.conf <<'EOF'
port = 15499
password_encryption = 'scram-sha-256'
log_connections = on
EOF
sed -i 's/\(host .*127.0.0.1\/32 *\)trust/\1scram-sha-256/' ~/exp/pgdata/pg_hba.conf
PGBIN=~/srvvenv/lib/python3.12/site-packages/pgserver/pginstall/bin
$PGBIN/pg_ctl -D ~/exp/pgdata stop -w
$PGBIN/pg_ctl -D ~/exp/pgdata -l ~/exp/pg.log -o "-h 127.0.0.1 -k $HOME/exp/pgdata" start -w
$PGBIN/psql -h $HOME/exp/pgdata -p 15499 -U postgres -c \
  "CREATE ROLE rotuser LOGIN PASSWORD 'pw-v1'; CREATE DATABASE rotdb OWNER rotuser;"

# Redis 6.2.14
mkdir -p ~/exp/redis
printf 'bind 127.0.0.1\nport 16399\nrequirepass rpw-v1\ndir %s/exp/redis\ndaemonize yes\nsave ""\n' "$HOME" > ~/exp/redis/redis.conf
~/srvvenv/lib/python3.12/site-packages/redislite/bin/redis-server ~/exp/redis/redis.conf
```

## Running

```bash
.venv/bin/python exp_asyncpg.py 127.0.0.1 15499 \
  "postgresql://postgres@/postgres?host=$HOME/exp/pgdata&port=15499"
.venv/bin/python exp_redis.py "redis://127.0.0.1:16399/0" rpw-v1
.venv/bin/python exp_callsite_shapes.py \
  "postgresql://rotuser:STALE-PASSWORD@127.0.0.1:15499/rotdb" "redis://127.0.0.1:16399/0"
```

`exp_asyncpg.py` leaves `rotuser`'s password at `pw-v3`; it resets to `pw-v1` on
its next run, but the other two scripts expect `pw-v1`, so re-run them after an
`ALTER ROLE rotuser PASSWORD 'pw-v1'`.

`exp_floor_versions.py` needs its own venv:

```bash
uv venv ~/floorvenv
uv pip install --python ~/floorvenv/bin/python "asyncpg==0.30.0" "redis==5.0.0"
~/floorvenv/bin/python exp_floor_versions.py 127.0.0.1 15499 "redis://127.0.0.1:16399/0"
```
