"""Regression smoke test for bug #694 (cold-start GitHub Events flood).

Run against a freshly wiped stack to verify the 8-layer defense is active:

    just dev-fresh              # wipes volumes, reseeds
    uv run python infra/scripts/smoke_test_694.py \\
        --repo owner/sandbox --install-id 12345678

What it asserts:

1. The stack starts in a cold state (no cursor for the target repo).
2. A ``check_run.completed`` self-healing trigger can be registered.
3. After at least one poll cycle, ``poller_cursors.last_event_id`` is
   populated -- proof Layer 2 (HWM filter) persisted the high-water mark.
4. The self-healing trigger's ``fire_count`` is 0 -- proof no cold-start
   replay leaked through to trigger evaluation.

Exit code 0 on success, 1 on any assertion failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import asyncpg
import httpx


async def _get_trigger_fire_count(client: httpx.AsyncClient, trigger_name: str) -> int | None:
    resp = await client.get("/triggers")
    resp.raise_for_status()
    body = resp.json()
    for trig in body.get("triggers", []):
        if trig.get("name") == trigger_name:
            return int(trig.get("fire_count", 0))
    return None


async def _assert_cold_state(pool: asyncpg.Pool, repo: str) -> None:
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM poller_cursors WHERE repo = $1", repo)
    if count and count > 0:
        msg = f"Stack is not fresh: cursor already exists for {repo}. Run `just dev-fresh` first."
        raise SystemExit(msg)
    print(f"OK fresh state: 0 cursors for {repo}")


async def _register_trigger(
    client: httpx.AsyncClient,
    name: str,
    repo: str,
    install_id: str,
    workflow_id: str,
) -> None:
    resp = await client.post(
        "/triggers",
        json={
            "name": name,
            "event": "check_run.completed",
            "repository": repo,
            "workflow_id": workflow_id,
            "installation_id": install_id,
            "created_by": "smoke-test-694",
        },
    )
    if resp.status_code >= 300:
        msg = f"Trigger registration failed: {resp.status_code} {resp.text}"
        raise SystemExit(msg)
    print(f"OK registered trigger '{name}' against {repo}")


async def _assert_hwm_persisted(pool: asyncpg.Pool, repo: str) -> tuple[str, str]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT etag, last_event_id FROM poller_cursors WHERE repo = $1",
            repo,
        )
    if row is None:
        msg = f"FAIL: no cursor persisted for {repo} after poll cycle. Poller may not be running."
        raise SystemExit(msg)
    etag = str(row["etag"] or "")
    last_event_id = str(row["last_event_id"] or "")
    if not last_event_id:
        msg = (
            f"FAIL: cursor for {repo} has empty last_event_id. "
            "Layer 2 (HWM filter) is not persisting -- bug #694 could recur."
        )
        raise SystemExit(msg)
    return etag, last_event_id


async def main(
    api_url: str,
    db_url: str,
    repo: str,
    install_id: str,
    workflow_id: str,
    wait_seconds: int,
) -> int:
    trigger_name = "smoke-test-694-self-healing"

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    if pool is None:
        msg = f"Could not connect to database at {db_url}"
        raise SystemExit(msg)
    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=30.0) as client:
            await _assert_cold_state(pool, repo)
            await _register_trigger(client, trigger_name, repo, install_id, workflow_id)

            print(f"Waiting {wait_seconds}s for poll cycle (default interval 60s + margin)...")
            await asyncio.sleep(wait_seconds)

            etag, last_event_id = await _assert_hwm_persisted(pool, repo)

            fires = await _get_trigger_fire_count(client, trigger_name)
            if fires is None:
                msg = f"FAIL: trigger '{trigger_name}' missing from /triggers list"
                raise SystemExit(msg)
            if fires != 0:
                msg = (
                    f"FAIL #694 REGRESSION: {fires} spurious fire(s) detected "
                    f"on fresh stack for trigger '{trigger_name}'. Expected 0."
                )
                raise SystemExit(msg)

        etag_preview = etag[:32] + "..." if len(etag) > 32 else etag
        print(f"OK: etag={etag_preview} last_event_id={last_event_id} fires=0")
        print("PASS: bug #694 regression check clean.")
        return 0
    finally:
        await pool.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:9137",
        help="Base URL for syn-api (no /api/v1 prefix on dev-fresh stack).",
    )
    parser.add_argument(
        "--db-url",
        default="postgresql://syn:syn_dev_password@localhost:5432/syn",
        help="Async DSN for the syn Postgres database.",
    )
    parser.add_argument("--repo", required=True, help="owner/repo to poll.")
    parser.add_argument(
        "--install-id",
        required=True,
        help="GitHub App installation ID for the target repo.",
    )
    parser.add_argument(
        "--workflow-id",
        default="wf-smoke-694",
        help="Workflow ID to link to the self-healing trigger.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=90,
        help="Seconds to wait for the poll cycle (default: 90).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        sys.exit(
            asyncio.run(
                main(
                    api_url=args.api_url,
                    db_url=args.db_url,
                    repo=args.repo,
                    install_id=args.install_id,
                    workflow_id=args.workflow_id,
                    wait_seconds=args.wait_seconds,
                )
            )
        )
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(str(exc), file=sys.stderr)
        raise
