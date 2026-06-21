# Codex CLI Observability Surface for syntropic137

Date: 2026-06-20
Host cwd during research: `/data/projects/synstress`
Codex version: `codex-cli 0.141.0`

This maps the local Codex CLI surfaces that an event-exporter adapter can use to populate syntropic137 `agent_events` similarly to Claude hook telemetry. Evidence is from this box only.

## Commands Run

| Purpose | Command |
|---|---|
| Locate/version/help | `command -v codex && codex --version && codex --help` |
| Exec flags and JSON stream flag | `codex exec --help` |
| Review/debug/features/app-server flags | `codex review --help`, `codex debug --help`, `codex features list`, `codex app-server --help`, `codex doctor --help` |
| Dotdir inventory | `find /home/ubuntu/.codex -maxdepth 3 -type f -printf ...` and `find /home/ubuntu/.codex -maxdepth 2 -type d -printf ...` |
| Config/hook inspection | `sed -n ... /home/ubuntu/.codex/config.toml`, `/home/ubuntu/.codex/config.json`, `/home/ubuntu/.codex/hooks.json`, `/home/ubuntu/.codex/version.json` |
| Session inventory/schema | `find /home/ubuntu/.codex/sessions -type f ...`, `jq ... /home/ubuntu/.codex/sessions/2026/06/20/*.jsonl` |
| Live JSON stream probe | `codex --ask-for-approval never exec --json --skip-git-repo-check --sandbox read-only -C /tmp 'Reply exactly: OK' > /tmp/codex-json-probe.jsonl` |
| SQLite schema/read-only samples | Python `sqlite3.connect('file:/home/ubuntu/.codex/state_5.sqlite?mode=ro', uri=True)` and same for `logs_2.sqlite`, `goals_1.sqlite`, `memories_1.sqlite` |
| Install package path | `file /home/ubuntu/.local/bin/codex`, `file /home/ubuntu/.bun/bin/codex`, `find /home/ubuntu/.bun/install/global/node_modules/@openai ...` |

Note: `sqlite3` CLI is not installed, so Python's standard `sqlite3` module was used read-only for schema and row inspection.

## Surface Inventory

### 1. `codex exec --json` live event stream

`codex exec --json` prints JSONL events to stdout. A minimal probe produced `/tmp/codex-json-probe.jsonl` with this shape:

```json
{"type":"thread.started","thread_id":"019ee632-bce1-7b20-9833-1c13fb2de60e"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"OK"}}
{"type":"turn.completed","usage":{"input_tokens":18594,"cached_input_tokens":4992,"output_tokens":5,"reasoning_output_tokens":0}}
```

This is the cleanest real-time extraction source for non-interactive Codex runs. It gives lifecycle and turn token usage without scraping internal rollout files. It does not include timestamps in the events, so the adapter must stamp receipt time if it needs event times.

Expected event families from help/user prompt and observed runs:

| Stream event | Observed fields | Adapter use |
|---|---|---|
| `thread.started` | `thread_id` | `agent_session_started` |
| `turn.started` | no id in observed probe | `agent_turn_started` |
| `item.completed` | `item.id`, `item.type`, type-specific payload | tool/message event, depending on `item.type` |
| `turn.completed` | `usage.input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens` | `agent_token_usage_recorded`, run/turn completion |

### 2. Persisted rollout JSONL

Codex writes per-session rollout files under:

`/home/ubuntu/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<thread_id>.jsonl`

Example from the JSON probe:

`/home/ubuntu/.codex/sessions/2026/06/20/rollout-2026-06-20T20-02-25-019ee632-bce1-7b20-9833-1c13fb2de60e.jsonl`

Observed top-level shape:

```json
{"timestamp":"...","type":"session_meta","payload":{...}}
{"timestamp":"...","type":"response_item","payload":{...}}
{"timestamp":"...","type":"event_msg","payload":{...}}
{"timestamp":"...","type":"turn_context","payload":{...}}
```

Observed `session_meta` fields:

| Field | Meaning |
|---|---|
| `payload.id` | thread/session id |
| `payload.timestamp` | session creation time |
| `payload.cwd` | run cwd |
| `payload.originator` | e.g. `codex_exec` |
| `payload.cli_version` | e.g. `0.141.0` |
| `payload.source` | e.g. `exec` |
| `payload.thread_source` | e.g. `user` |
| `payload.model_provider` | e.g. `openai` |
| `payload.git` | object or `null`; in repo runs includes commit/branch/repository URL data |

Observed `event_msg.payload.type` values in the probe:

| Type | Key fields | Adapter use |
|---|---|---|
| `task_started` | `turn_id`, `started_at`, `model_context_window`, `collaboration_mode_kind` | lifecycle start |
| `user_message` | `message`, `text_elements`, image fields | user prompt event |
| `agent_message` | `message`, `phase`, optional `memory_citation` | assistant output event |
| `token_count` | `info.total_token_usage`, `info.last_token_usage`, `rate_limits` | authoritative persisted token totals |
| `task_complete` | `turn_id`, `completed_at`, `duration_ms`, `time_to_first_token_ms`, `last_agent_message` | lifecycle completion and duration |

Example token payload from the probe rollout:

```json
{
  "type": "token_count",
  "info": {
    "total_token_usage": {
      "input_tokens": 18594,
      "cached_input_tokens": 4992,
      "output_tokens": 5,
      "reasoning_output_tokens": 0,
      "total_tokens": 18599
    },
    "last_token_usage": {
      "input_tokens": 18594,
      "cached_input_tokens": 4992,
      "output_tokens": 5,
      "reasoning_output_tokens": 0,
      "total_tokens": 18599
    },
    "model_context_window": 258400
  },
  "rate_limits": {
    "limit_id": "codex",
    "primary": {"used_percent": 2.0, "window_minutes": 300},
    "secondary": {"used_percent": 7.0, "window_minutes": 10080},
    "plan_type": "prolite"
  }
}
```

Tool actions are persisted as `response_item` records. In the current research session rollout, observed `response_item.payload.type` counts included `function_call`, `function_call_output`, `message`, and `reasoning`. Earlier and richer sessions also use these same payload types. For shell commands executed through the current Codex tool layer, `function_call` contains the tool name and serialized arguments; `function_call_output` contains the call id and output envelope. These can be mapped to syntropic `tool_started` and `tool_completed` events by pairing on `call_id`.

### 3. Thread state SQLite

Codex stores a thread index in:

`/home/ubuntu/.codex/state_5.sqlite`

Relevant table:

```sql
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    cwd TEXT NOT NULL,
    title TEXT NOT NULL,
    sandbox_policy TEXT NOT NULL,
    approval_mode TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    has_user_event INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    archived_at INTEGER,
    git_sha TEXT,
    git_branch TEXT,
    git_origin_url TEXT,
    cli_version TEXT NOT NULL DEFAULT '',
    first_user_message TEXT NOT NULL DEFAULT '',
    agent_nickname TEXT,
    agent_role TEXT,
    memory_mode TEXT NOT NULL DEFAULT 'enabled',
    model TEXT,
    reasoning_effort TEXT,
    agent_path TEXT,
    created_at_ms INTEGER,
    updated_at_ms INTEGER,
    thread_source TEXT,
    preview TEXT NOT NULL DEFAULT ''
)
```

This is the best run index and join table. Recent rows showed:

| Column | Use |
|---|---|
| `id` | session/thread id |
| `rollout_path` | persisted JSONL transcript path |
| `created_at`, `updated_at`, `created_at_ms`, `updated_at_ms` | lifecycle timestamps |
| `source` | `exec`, `{"subagent":"review"}`, etc. |
| `cwd` | workspace mapping |
| `title`, `preview`, `first_user_message` | prompt/title |
| `sandbox_policy`, `approval_mode` | execution policy |
| `tokens_used` | aggregate token total; useful but less detailed than rollout `token_count` |
| `git_sha`, `git_branch`, `git_origin_url` | repository snapshot at run start |
| `cli_version`, `model`, `model_provider`, `reasoning_effort` | model metadata |

### 4. Prompt history JSONL

Codex stores user prompt history in:

`/home/ubuntu/.codex/history.jsonl`

Shape:

```json
{"session_id":"019e7081-c3e3-7833-9a35-11b03d58cb3d","ts":1780004082,"text":"test 1 2"}
```

This is not enough for tool/tokens, but it is useful for backfilling user-intent events or matching externally launched runs to thread ids.

### 5. Logs SQLite

Codex stores internal logs in:

`/home/ubuntu/.codex/logs_2.sqlite`

Relevant schema:

```sql
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    ts_nanos INTEGER NOT NULL,
    level TEXT NOT NULL,
    target TEXT NOT NULL,
    feedback_log_body TEXT,
    module_path TEXT,
    file TEXT,
    line INTEGER,
    thread_id TEXT,
    process_uuid TEXT,
    estimated_bytes INTEGER NOT NULL DEFAULT 0
)
```

Observed recent rows were low-level `TRACE` inotify events, often without `thread_id`. This database is useful for debugging exporter failures but should not be the primary agent_events source.

### 6. Goals and memories SQLite

Additional local stores:

`/home/ubuntu/.codex/goals_1.sqlite`

```sql
CREATE TABLE thread_goals (
    thread_id TEXT PRIMARY KEY NOT NULL,
    goal_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    token_budget INTEGER,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    time_used_seconds INTEGER NOT NULL DEFAULT 0,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
)
```

`/home/ubuntu/.codex/memories_1.sqlite` contains memory extraction jobs and `stage1_outputs`. These are not required for a first event exporter, but `thread_goals` can enrich sessions with objective/status/budget if syntropic wants Codex goal telemetry.

### 7. Config and hooks

Observed config files:

| Path | Purpose |
|---|---|
| `/home/ubuntu/.codex/config.toml` | primary Codex config, trusted projects, plugins, MCP servers, hook trust state |
| `/home/ubuntu/.codex/config.json` | legacy/tool config, observed MCP tool entry |
| `/home/ubuntu/.codex/hooks.json` | hook definitions |
| `/home/ubuntu/.codex/version.json` | latest version check state |
| `/home/ubuntu/.codex/auth.json` | auth material; do not scrape |

Observed `/home/ubuntu/.codex/hooks.json` shape:

```json
{
  "hooks": {
    "PostToolUse": [
      {"matcher": "^Bash$", "hooks": [{"type": "command", "command": "atuin hook codex"}]}
    ],
    "PostToolUseFailure": [
      {"matcher": "^Bash$", "hooks": [{"type": "command", "command": "atuin hook codex"}]}
    ],
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "/home/ubuntu/.local/bin/dcg"}]},
      {"matcher": "^Bash$", "hooks": [{"type": "command", "command": "atuin hook codex"}]}
    ]
  }
}
```

`codex features list` reports `hooks` as stable and enabled. Global help includes `--dangerously-bypass-hook-trust`. `config.toml` stores trusted hashes under `[hooks.state]`.

I attempted an isolated hook payload probe with a temporary `CODEX_HOME`; it failed authentication because `CODEX_HOME` also controls auth. I did not copy auth credentials into the temp directory. Therefore this report confirms hook existence/configuration and trust state, but not the exact stdin/env payload delivered to hook commands. For the adapter, persisted rollout + `--json` are more concrete than hook payloads today.

### 8. OTLP / telemetry

No normal `codex exec` OTLP flag was found in `codex exec --help`. `codex app-server --help` exposes:

`--analytics-default-enabled`

with help text saying app-server analytics are disabled by default and can be opted in via an `[analytics]` section in `config.toml`, referencing advanced metrics docs. That is app-server analytics, not a confirmed per-agent OTLP export channel for CLI runs.

`codex features list` includes `runtime_metrics` as `under development false`. I found no concrete, enabled `codex exec` OTLP/exporter surface on this box.

## Extraction Recipes by Event Type

### Session lifecycle

Primary live path:

1. Launch Codex as `codex exec --json ...`.
2. On `{"type":"thread.started","thread_id":...}` emit `AgentSessionStarted`.
3. On `{"type":"turn.started"}` emit `AgentTurnStarted`.
4. On `{"type":"turn.completed","usage":...}` emit `AgentTurnCompleted` and token usage.

Backfill/scrape path:

1. Read new/updated rows from `/home/ubuntu/.codex/state_5.sqlite:threads`.
2. Use `threads.id` as `session_id`.
3. Use `threads.rollout_path` to parse the rollout JSONL.
4. Emit session start from `session_meta.payload.timestamp` or `threads.created_at_ms`.
5. Emit task completion from `event_msg.payload.type == "task_complete"` with `completed_at`, `duration_ms`, `time_to_first_token_ms`.

Adapter fields:

| syntropic field | Codex source |
|---|---|
| `session_id` | `thread.started.thread_id`, `session_meta.payload.id`, `threads.id` |
| `started_at` | rollout `session_meta.timestamp` / `payload.timestamp`, or `threads.created_at_ms` |
| `completed_at` | `event_msg.task_complete.completed_at` or `threads.updated_at_ms` |
| `cwd/workspace` | `session_meta.payload.cwd`, `turn_context.payload.cwd`, `threads.cwd` |
| `cli_version` | `session_meta.payload.cli_version`, `threads.cli_version` |
| `source` | `session_meta.payload.source`, `threads.source` |
| `model` | `threads.model`, `turn_context.payload.model` |
| `provider` | `session_meta.payload.model_provider`, `threads.model_provider` |

### Tokens and cost

Best source:

`turn.completed.usage` from `--json` for live runs.

Best persisted source:

`event_msg.payload.type == "token_count"` in rollout JSONL:

`payload.info.last_token_usage` and `payload.info.total_token_usage`.

Aggregate fallback:

`state_5.sqlite:threads.tokens_used`.

Cost:

Codex artifacts on this box do not store dollar cost. To compute per-run cost, join token usage with the model from `threads.model` or `turn_context.payload.model` and an external pricing table maintained by syntropic137. Preserve raw token dimensions:

| Dimension | Source |
|---|---|
| input tokens | `input_tokens` |
| cached input tokens | `cached_input_tokens` |
| output tokens | `output_tokens` |
| reasoning output tokens | `reasoning_output_tokens` |
| total tokens | rollout `total_tokens` or computed |

Use `last_token_usage` for per-turn events and `total_token_usage` or `threads.tokens_used` for session rollups. Be careful with compaction/resume: `total_token_usage` in later rollout records is the best observed persisted cumulative counter for a thread, while the live stream `turn.completed.usage` is per invocation/turn.

### Tool actions

Live source:

`--json` `item.completed` events when `item.type` is a tool-related item. The minimal probe only had `agent_message`; tool-using runs should produce additional `item.type` values.

Persisted source:

Rollout `response_item` rows:

| Payload type | Adapter event |
|---|---|
| `function_call` | `ToolUseStarted` |
| `function_call_output` | `ToolUseCompleted` |
| `message` role `assistant` | assistant message |
| `reasoning` | reasoning summary, optional observability event |

Pair `function_call` and `function_call_output` by `payload.call_id`. For shell commands, parse the serialized `arguments` JSON to extract command, cwd/workdir, sandbox intent, and max output settings. The current Codex tool layer records command execution through these function-call artifacts rather than Claude's richer hook payload channel.

### File changes

Codex does not expose a first-class "file changed" event in the observed stream. Extraction options:

1. Infer from tool actions:
   - `apply_patch` function calls contain patch hunks. Emit file-change intent from patch paths before completion, then result from output.
   - shell commands may mutate files. Only commands can be recorded directly; file effects require post-run diff.
2. Snapshot git/worktree before and after:
   - Use `threads.git_sha`, `threads.git_branch`, `threads.git_origin_url` as starting repo context.
   - At session end, run `git status --porcelain=v1`, `git diff --name-status`, and optionally `git diff --stat` in `threads.cwd`.
3. If running in syntropic-controlled workspace, wrap the Codex process and collect filesystem diff at container stop.

Recommended event mapping:

| Event | How to extract |
|---|---|
| `FilePatchProposed` | `response_item.function_call` where name/arguments indicate `apply_patch` |
| `FilePatchApplied` | matching `function_call_output` success |
| `WorkspaceDiffObserved` | post-run `git diff --name-status`/`git status` snapshot |

### Git and commit events

Codex records repo snapshot metadata in `state_5.sqlite:threads`:

`git_sha`, `git_branch`, `git_origin_url`.

This is not a commit event stream. To detect commits made by Codex:

1. Capture starting `git_sha` from `threads.git_sha` or `git rev-parse HEAD` before launch.
2. Parse tool actions for shell commands matching `git commit`, `git merge`, `git rebase`, `git tag`, `git push`, etc.
3. At session end, compare `git rev-parse HEAD` to starting SHA.
4. If changed, emit `GitCommitCreated` for new commits from `git log --format` between old and new SHA.
5. If `git push` appears in tool actions, emit `GitPushAttempted` and use command exit output for success/failure.

There is no observed Codex-native commit event.

### Messages

Persisted rollout records:

| Codex source | Meaning |
|---|---|
| `response_item.payload.type == "message"` and `role == "user"` | prompt/context message |
| `event_msg.payload.type == "user_message"` | user-visible prompt event |
| `response_item.payload.type == "message"` and `role == "assistant"` | assistant output |
| `event_msg.payload.type == "agent_message"` | assistant visible output |

For user-facing syntropic events, prefer `event_msg.user_message` and `event_msg.agent_message`. For complete replay/debug, also store raw `response_item.message` records in an opaque payload table because they include model-visible developer/system context.

## Gaps vs Claude Hook Channel

| Area | Codex status | Gap |
|---|---|---|
| Pre/post tool hook channel | Exists and is enabled via `hooks.json`; exact payload not verified here | Cannot yet rely on hook payload parity with Claude |
| Live JSON stream | `codex exec --json` is clean and concrete | Non-interactive only; no timestamps in observed events |
| Persisted transcript | Rich rollout JSONL under `~/.codex/sessions` | Internal-ish schema; may include large model-visible context and sensitive prompts |
| Token usage | Strong: live `turn.completed.usage`, persisted `token_count` | No dollar cost; must price externally |
| Tool actions | Present as Responses-style `function_call`/`function_call_output` in rollout | Less direct than Claude hooks; command/file effects require parsing and diffing |
| File changes | Not first-class in observed events | Need patch parsing plus git/filesystem diff |
| Git commits | Starting git metadata in thread index | Need command parsing plus before/after git comparison |
| OTLP | No confirmed normal CLI OTLP surface; app-server analytics exists separately | Cannot use native OTLP as Claude equivalent |
| Interactive TUI | Rollout files and SQLite still exist | No direct `--json` stream unless launched via `exec`; adapter must tail files/DB |

## Recommended Adapter Design

Build two ingestion modes.

### Mode A: wrapper for controlled `codex exec`

Launch:

```bash
codex exec --json [normal flags] "$prompt"
```

Exporter behavior:

1. Read stdout JSONL.
2. Emit lifecycle from `thread.started`, `turn.started`, `turn.completed`.
3. Emit token usage from `turn.completed.usage`.
4. Capture `thread_id`.
5. After process exits, join `thread_id` to `/home/ubuntu/.codex/state_5.sqlite:threads`.
6. Parse `threads.rollout_path` for richer timestamps, tool calls, messages, and `token_count`.
7. Run git/worktree diff in `threads.cwd` if cwd is a repository.

This mode should be the default for syntropic-managed Codex runs.

### Mode B: scraper for interactive/unwrapped Codex

Watch:

| Path | What to scrape |
|---|---|
| `/home/ubuntu/.codex/state_5.sqlite` | new/updated `threads` rows |
| `/home/ubuntu/.codex/sessions/**/*.jsonl` | rollout records by `rollout_path` |
| `/home/ubuntu/.codex/history.jsonl` | prompt backfill only |
| `/home/ubuntu/.codex/goals_1.sqlite` | optional goal status/budget |

Cursor strategy:

1. Maintain `thread_id -> rollout_path -> byte_offset` cursor.
2. Poll `state_5.sqlite` for `threads.updated_at_ms > watermark`.
3. Tail rollout JSONL from the previous byte offset.
4. Dedupe by `(thread_id, rollout_path, line_number)` or hash of raw line.
5. Emit normalized syntropic events.

Do not scrape:

| Path | Reason |
|---|---|
| `/home/ubuntu/.codex/auth.json` | auth secrets |
| `/home/ubuntu/.codex/config.toml` full contents | can contain MCP bearer tokens; only read safe non-secret fields if needed |
| `/home/ubuntu/.codex/logs_2.sqlite` as primary source | too noisy and not reliably thread-associated |

## Concrete Scrape Mapping

| syntropic event | Primary Codex source | Fallback |
|---|---|---|
| `AgentSessionStarted` | `--json thread.started` + rollout `session_meta` | `state_5.threads` new row |
| `AgentTurnStarted` | `--json turn.started` | rollout `event_msg.task_started` |
| `UserMessageRecorded` | rollout `event_msg.user_message` | `history.jsonl` |
| `AgentMessageRecorded` | rollout `event_msg.agent_message` | `--json item.completed` agent_message |
| `ToolUseStarted` | rollout `response_item.function_call` | `--json item.completed` tool item |
| `ToolUseCompleted` | rollout `response_item.function_call_output` | hook PostToolUse if payload is later verified |
| `TokenUsageRecorded` | `--json turn.completed.usage` | rollout `event_msg.token_count`; `threads.tokens_used` |
| `AgentTurnCompleted` | `--json turn.completed` | rollout `event_msg.task_complete` |
| `AgentSessionCompleted` | process exit + rollout `task_complete` | `threads.updated_at_ms` inactivity |
| `WorkspaceDiffObserved` | post-run git diff/status | parse `apply_patch` calls |
| `GitCommitCreated` | before/after git SHA comparison | parse shell command tool calls |
| `RateLimitObserved` | rollout `event_msg.token_count.rate_limits` | none |

## Open Questions / Follow-up Probes

1. Verify Codex hook command payload using a non-secret test auth profile or a disposable API key. The temp `CODEX_HOME` probe failed with `401 Unauthorized`, and copying real auth was intentionally avoided.
2. Run a tool-heavy controlled prompt under `codex exec --json` and capture the exact live `item.completed.item.type` values for shell/tool calls. The current minimal probe only produced `agent_message`; the persisted active session confirms `function_call`/`function_call_output` in rollout.
3. Confirm whether app-server `[analytics]` can emit useful local metrics, but do not block the adapter on it. The normal CLI evidence points to JSONL/SQLite, not OTLP.

## Bottom Line

For syntropic137, the practical Codex adapter should not wait for native OTLP. Use `codex exec --json` when syntropic launches the run, and always join to `~/.codex/state_5.sqlite` plus the rollout JSONL for authoritative timestamps, tool calls, messages, git metadata, token totals, rate limits, and task durations. For interactive Codex sessions, tail `state_5.sqlite` and `sessions/**/*.jsonl` with cursors. Compute cost externally from raw token dimensions and model metadata. Detect file and git events with patch parsing plus before/after repository snapshots because Codex does not emit first-class file-change or commit events in the observed artifacts.
