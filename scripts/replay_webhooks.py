"""Replay recorded GitHub webhooks against a running dashboard.

Usage:
    uv run python scripts/replay_webhooks.py fixtures/webhooks/check_run_failure.jsonl
    uv run python scripts/replay_webhooks.py --speed 10 --target http://localhost:8137 <file>
    uv run python scripts/replay_webhooks.py --no-signature <file>

Reads JSONL files produced by WebhookRecorderMiddleware and POSTs each event
to the dashboard with recorded headers. Supports speed control and
signature stripping.

See ADR-041: Offline Development Mode and Webhook Recording.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx


async def replay(
    filepath: Path,
    target: str,
    speed: float,
    no_signature: bool,
) -> int:
    """Replay a JSONL webhook recording.

    Returns exit code (0 = success).
    """
    if not filepath.exists():
        print(f"File not found: {filepath}", file=sys.stderr)
        return 1

    lines = filepath.read_text().strip().splitlines()
    if not lines:
        print(f"Empty recording: {filepath}", file=sys.stderr)
        return 1

    # Parse metadata (first line)
    metadata = json.loads(lines[0])
    if metadata.get("_type") == "metadata":
        event_lines = lines[1:]
        print(f"Recording: {metadata.get('compound_event', 'unknown')}")
        print(f"  Recorded at: {metadata.get('recorded_at', 'unknown')}")
        print(f"  Delivery ID: {metadata.get('delivery_id', 'unknown')}")
    else:
        # No metadata header — treat all lines as events
        event_lines = lines

    print(f"  Events: {len(event_lines)}")
    print(f"  Target: {target}")
    print(f"  Speed: {speed}x")
    print()

    prev_offset_ms = 0
    success_count = 0
    error_count = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, line in enumerate(event_lines):
            entry = json.loads(line)

            # Respect timing
            offset_ms = entry.get("_offset_ms", 0)
            if speed > 0 and offset_ms > prev_offset_ms:
                delay = (offset_ms - prev_offset_ms) / 1000.0 / speed
                if delay > 0.01:
                    await asyncio.sleep(delay)
            prev_offset_ms = offset_ms

            # Build headers
            recorded_headers = entry.get("headers", {})
            headers: dict[str, str] = {}

            for key, value in recorded_headers.items():
                if no_signature and key == "x-hub-signature-256":
                    continue
                headers[key] = value

            # Ensure content-type is set
            if "content-type" not in headers:
                headers["content-type"] = "application/json"

            # POST the webhook
            body = entry.get("body", {})
            try:
                resp = await client.post(
                    f"{target}/webhooks/github",
                    content=json.dumps(body).encode(),
                    headers=headers,
                )
                status = resp.status_code
                if 200 <= status < 300:
                    result_data = resp.json() if resp.content else {}
                    fired = result_data.get("triggers_fired", [])
                    print(f"  [{i + 1}/{len(event_lines)}] {status} OK — triggers fired: {fired}")
                    success_count += 1
                else:
                    print(f"  [{i + 1}/{len(event_lines)}] {status} ERROR — {resp.text[:200]}")
                    error_count += 1
            except httpx.RequestError as e:
                print(f"  [{i + 1}/{len(event_lines)}] FAILED — {e}")
                error_count += 1

    print(f"\nDone: {success_count} succeeded, {error_count} failed")
    return 1 if error_count > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay recorded GitHub webhooks against a dashboard"
    )
    parser.add_argument("file", type=Path, help="JSONL recording file to replay")
    parser.add_argument(
        "--target",
        default="http://localhost:8137",
        help="Target dashboard URL (default: http://localhost:8137)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=0.0,
        help="Playback speed multiplier (0 = instant, 10 = 10x faster). Default: instant.",
    )
    parser.add_argument(
        "--no-signature",
        action="store_true",
        help="Strip webhook signature headers (for testing without secret)",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(replay(args.file, args.target, args.speed, args.no_signature))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
