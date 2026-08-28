"""Validate that a codex run's raw session_log matches the recorded observability.

Given a codex execution (or a single session), this:
  1. fetches the raw `codex exec --json` session_log (from the conversations API),
  2. derives the observability events that SHOULD have been recorded, straight
     from the codex --json taxonomy (mirrors CodexStreamProcessor),
  3. fetches what was ACTUALLY recorded via the syn-api read models
     (observability tools / tokens, costs),
  4. diffs the two and prints a PASS/FAIL report (non-zero exit on any mismatch).

This is the "check the session log and compare it against every event it should
have produced" check, made repeatable. It is codex-specific: the expected
taxonomy encodes codex's mapping (input_tokens INCLUDES cached; reasoning folds
into output; command_execution -> Bash; file_change -> a synthetic Edit pair;
exactly one session_summary; non-JSON noise lines produce no events).

Run via:
    uv run python scripts/validate_codex_observability.py --execution exec-XXXX
    uv run python scripts/validate_codex_observability.py --session <session_id>
    uv run python scripts/validate_codex_observability.py --session-log run.jsonl   # offline: derive-only

Auth/base-url default to the local dev stack; override with --base-url / --user /
--password (or SYN_API_PASSWORD in the environment).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import cast

# --- codex --json taxonomy constants (mirror CodexStreamProcessor) -----------
_TYPE_ITEM_STARTED = "item.started"
_TYPE_ITEM_COMPLETED = "item.completed"
_TYPE_TURN_COMPLETED = "turn.completed"
_ITEM_COMMAND = "command_execution"
_ITEM_FILE_CHANGE = "file_change"

# --- recorded event_type values (agent_events / API operation_type) ----------
_EVT_TOOL_STARTED = "tool_execution_started"
_EVT_TOOL_COMPLETED = "tool_execution_completed"


@dataclass(frozen=True)
class ExpectedEvents:
    """Observability events a codex session_log should produce."""

    token_usage_events: int
    tool_started: int
    tool_completed: int
    session_summary: int
    fresh_input_tokens: int
    cache_read_tokens: int
    output_tokens: int
    turns: int
    noise_lines: int


@dataclass(frozen=True)
class RecordedEvents:
    """Observability actually recorded, read back from syn-api."""

    tool_started: int
    tool_completed: int
    input_tokens: int
    cache_read_tokens: int
    output_tokens: int
    turns: int
    tool_calls: int
    total_cost_usd: float


def _item_type(event: dict[str, object]) -> str | None:
    item = event.get("item")
    if isinstance(item, dict):
        item_typed = cast("dict[str, object]", item)
        t = item_typed.get("type")
        if isinstance(t, str):
            return t
    return None


def _usage_int(usage: dict[str, object], key: str) -> int:
    val = usage.get(key)
    return val if isinstance(val, int) else 0


def derive_expected(lines: list[str]) -> ExpectedEvents:
    """Derive the expected observability events from raw codex --json lines.

    Independent re-derivation of CodexStreamProcessor's taxonomy, so a divergence
    between this and the recorded events flags either a parser bug or a
    persistence/projection bug.
    """
    token_events = 0
    started = 0
    completed = 0
    fresh_input = 0
    cache_read = 0
    output = 0
    turns = 0
    noise = 0

    for raw in lines:
        line = raw.strip()
        if not line:
            continue  # blank line: not content, not noise
        if not line.startswith("{"):
            noise += 1  # interleaved CLI junk (deprecation warning, ERROR log, banner)
            continue
        try:
            parsed: object = json.loads(line)
        except json.JSONDecodeError:
            noise += 1
            continue
        if not isinstance(parsed, dict):
            noise += 1
            continue
        event = cast("dict[str, object]", parsed)
        etype = event.get("type")

        if etype == _TYPE_ITEM_STARTED and _item_type(event) == _ITEM_COMMAND:
            started += 1  # Bash start
        elif etype == _TYPE_ITEM_COMPLETED and _item_type(event) == _ITEM_COMMAND:
            completed += 1  # Bash complete
        elif etype == _TYPE_ITEM_COMPLETED and _item_type(event) == _ITEM_FILE_CHANGE:
            started += 1  # synthetic Edit start
            completed += 1  # synthetic Edit complete
        elif etype == _TYPE_TURN_COMPLETED:
            token_events += 1
            turns += 1
            usage_obj = event.get("usage")
            usage = cast("dict[str, object]", usage_obj) if isinstance(usage_obj, dict) else {}
            input_tokens = _usage_int(usage, "input_tokens")
            cached = _usage_int(usage, "cached_input_tokens")
            fresh_input += max(0, input_tokens - cached)
            cache_read += cached
            output += _usage_int(usage, "output_tokens") + _usage_int(
                usage, "reasoning_output_tokens"
            )
        # all other event types (thread.started, turn.started, item.started
        # file_change, item.completed agent_message) produce no observability.

    # The processor emits exactly one session_summary at end of stream.
    return ExpectedEvents(
        token_usage_events=token_events,
        tool_started=started,
        tool_completed=completed,
        session_summary=1,
        fresh_input_tokens=fresh_input,
        cache_read_tokens=cache_read,
        output_tokens=output,
        turns=turns,
        noise_lines=noise,
    )


# --- live fetch --------------------------------------------------------------


def _auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def _get_json(url: str, auth: str) -> object:
    req = urllib.request.Request(url, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"error: GET {url} -> HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"error: GET {url} failed ({exc.reason}). Is the stack up?") from exc


def _as_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _int_field(d: dict[str, object], key: str) -> int:
    val = d.get(key)
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val.lstrip("-").isdigit():
        return int(val)
    return 0


def _float_field(d: dict[str, object], key: str) -> float:
    val = d.get(key)
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return 0.0
    return 0.0


def fetch_session_log(base: str, session_id: str, auth: str) -> list[str]:
    """Fetch the raw codex session_log lines (verbatim) via the conversations API."""
    lines: list[str] = []
    offset = 0
    page = 500
    while True:
        url = f"{base}/api/v1/conversations/{session_id}?limit={page}&offset={offset}"
        payload = _as_dict(_get_json(url, auth))
        batch = _as_list(payload.get("lines"))
        for entry in batch:
            row = _as_dict(entry)
            raw = row.get("raw")
            if isinstance(raw, str):
                lines.append(raw)
        if len(batch) < page:
            break
        offset += page
    return lines


def fetch_recorded(base: str, session_id: str, auth: str) -> RecordedEvents:
    tools = _as_dict(_get_json(f"{base}/api/v1/observability/sessions/{session_id}/tools", auth))
    started = 0
    completed = 0
    for entry in _as_list(tools.get("executions")):
        row = _as_dict(entry)
        op = row.get("operation_type")
        if op == _EVT_TOOL_STARTED:
            started += 1
        elif op == _EVT_TOOL_COMPLETED:
            completed += 1
    # Some projections only surface completed ops; fall back to total_executions.
    if started == 0 and completed == 0:
        completed = _int_field(tools, "total_executions")

    tokens = _as_dict(_get_json(f"{base}/api/v1/observability/sessions/{session_id}/tokens", auth))
    cost = _as_dict(_get_json(f"{base}/api/v1/costs/sessions/{session_id}", auth))

    return RecordedEvents(
        tool_started=started,
        tool_completed=completed,
        input_tokens=_int_field(tokens, "input_tokens"),
        cache_read_tokens=_int_field(tokens, "cache_read_tokens"),
        output_tokens=_int_field(tokens, "output_tokens"),
        turns=_int_field(cost, "turns"),
        tool_calls=_int_field(cost, "tool_calls"),
        total_cost_usd=_float_field(tokens, "total_cost_usd")
        or _float_field(cost, "total_cost_usd"),
    )


def resolve_session_ids(base: str, execution_id: str, auth: str) -> list[str]:
    # `include_session_ids` defaults to FALSE: the array is unbounded and most
    # callers do not want it. A client that needs the IDs must ask. Without the
    # flag the field comes back null and this script cannot resolve anything -
    # which is exactly how it silently failed before.
    cost = _as_dict(
        _get_json(
            f"{base}/api/v1/costs/executions/{execution_id}?include_session_ids=true",
            auth,
        )
    )
    ids = [s for s in _as_list(cost.get("session_ids")) if isinstance(s, str)]
    if not ids:
        raise SystemExit(
            f"error: no sessions found for execution {execution_id}. "
            f"(session_count={cost.get('session_count')})"
        )
    return ids


# --- compare + report --------------------------------------------------------


@dataclass(frozen=True)
class Row:
    category: str
    expected: int
    recorded: int

    @property
    def ok(self) -> bool:
        return self.expected == self.recorded


def compare(expected: ExpectedEvents, recorded: RecordedEvents) -> list[Row]:
    return [
        Row("tool ops started", expected.tool_started, recorded.tool_started),
        Row("tool ops completed", expected.tool_completed, recorded.tool_completed),
        Row("turns (token_usage events)", expected.turns, recorded.turns),
        Row("input tokens (fresh)", expected.fresh_input_tokens, recorded.input_tokens),
        Row("cache-read tokens", expected.cache_read_tokens, recorded.cache_read_tokens),
        Row("output tokens", expected.output_tokens, recorded.output_tokens),
    ]


def _print_report(session_id: str, expected: ExpectedEvents, recorded: RecordedEvents) -> bool:
    rows = compare(expected, recorded)
    print(f"\n=== codex observability validation: session {session_id} ===")
    print(f"{'category':<30}{'expected':>12}{'recorded':>12}  status")
    print("-" * 68)
    all_ok = True
    for r in rows:
        status = "PASS" if r.ok else "FAIL"
        all_ok = all_ok and r.ok
        print(f"{r.category:<30}{r.expected:>12}{r.recorded:>12}  {status}")
    print("-" * 68)
    print(
        f"session_summary expected: {expected.session_summary} "
        f"(read-model reflects it via cost={recorded.total_cost_usd})"
    )
    print(f"noise (non-JSON) lines tolerated in session_log: {expected.noise_lines}")
    print(
        f"\nRESULT: {'PASS - all recorded observability matches the session_log' if all_ok else 'FAIL - see mismatches above'}"
    )
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--execution", help="execution id (validates every session in it)")
    group.add_argument("--session", help="a single session id")
    group.add_argument(
        "--session-log", help="offline: a raw codex --json file; derive expected only"
    )
    parser.add_argument("--base-url", default="http://localhost:8137")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default=os.environ.get("SYN_API_PASSWORD", "admin"))
    args = parser.parse_args()

    if args.session_log:
        expected = derive_expected(Path(args.session_log).read_text(encoding="utf-8").splitlines())
        print("Derived expected events from session_log (offline, no live compare):")
        print(f"  token_usage events : {expected.token_usage_events}")
        print(f"  tool started       : {expected.tool_started}")
        print(f"  tool completed     : {expected.tool_completed}")
        print(f"  session_summary    : {expected.session_summary}")
        print(f"  fresh input tokens : {expected.fresh_input_tokens}")
        print(f"  cache-read tokens  : {expected.cache_read_tokens}")
        print(f"  output tokens      : {expected.output_tokens}")
        print(f"  turns              : {expected.turns}")
        print(f"  noise lines        : {expected.noise_lines}")
        return 0

    auth = _auth_header(args.user, args.password)
    base = args.base_url.rstrip("/")
    session_ids = (
        [args.session] if args.session else resolve_session_ids(base, args.execution, auth)
    )

    all_ok = True
    for sid in session_ids:
        log_lines = fetch_session_log(base, sid, auth)
        if not log_lines:
            print(f"warning: no session_log lines for session {sid} (nothing to validate).")
            all_ok = False
            continue
        expected = derive_expected(log_lines)
        recorded = fetch_recorded(base, sid, auth)
        all_ok = _print_report(sid, expected, recorded) and all_ok

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
