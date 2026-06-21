# Obs L1 — Claude Observability Ground Truth (syntropic137, today)

**Scope:** Exactly how Claude observability works in syntropic137 *as built*, so it can be
generalized to other harnesses. Read-only research; no source modified.

**Repo:** `/data/projects/synstress` (syntropic137 + vendored `lib/agentic-primitives`).
All citations are `file:line` relative to that root.

---

## 0. The big picture: TWO ingestion routes, ONE table

Everything Claude emits lands in the TimescaleDB hypertable **`agent_events`**
(`time, event_type, session_id, execution_id, phase_id, data`). There are **two physically
distinct routes** that get data there, plus a third source-of-events (the watcher) that feeds
route A:

```
                                        ┌──────────────────────────────────────────┐
 Claude lifecycle hooks (observe.py) ──┐│ ROUTE A — HTTP collector (syn-collector)  │
 git hooks (post-commit, pre-push…)  ──┤│  POST /events  (EventBatch JSONL)         │──┐
 watcher (tails hooks.jsonl+transcript)┘│  POST /v1/metrics, /v1/logs (Claude OTLP) │  │
                                        └──────────────────────────────────────────┘  │
                                                                                       ▼
 Claude CLI stdout/stderr JSONL ───────► ROUTE B — in-orchestrator stream           agent_events
 (docker exec stream, no HTTP)           parse_jsonl_events → AgentEvent.from_dict ──► (TimescaleDB
                                         → EventBuffer → COPY into agent_events         hypertable)
```

- **Route A (collector, network):** `CollectedEvent` → dedup → `TimescaleDBObservabilityStore`
  → buffer → `agent_events`. Used by the **observability plugin git hooks/observe handler when
  pointed at a collector**, by the **OTLP channel**, and by the **watcher**.
- **Route B (orchestrator, in-process):** Claude CLI's own stdout/stderr JSONL is captured by the
  docker-exec stream adapter, parsed by `parse_jsonl_events`, mapped through `AgentEvent.from_dict`,
  and written to `agent_events` directly. This is how the **git hooks' stderr JSONL** and the
  **Claude CLI result/usage JSONL** reach the table during a workflow execution (no collector needed).

Both routes converge on the **same 6-column schema and the same `EventType` vocabulary.** An
exporter for a new harness only has to produce rows that fit that schema (see final section).

---

## 1. The observability PLUGIN + its git hooks

Lives in `lib/agentic-primitives/plugins/observability/`.

### 1a. Plugin manifest + Claude lifecycle hooks

- `.claude-plugin/plugin.json:1` — `name: observability`, v0.2.1, "emits structured JSONL events
  via agentic_events".
- `hooks/hooks.json:4-191` — registers 14 Claude Code lifecycle hooks, all invoking
  `${CLAUDE_PLUGIN_ROOT}/hooks/handlers/observe.py` (timeout 5s): `SessionStart`, `SessionEnd`,
  `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`,
  `Notification`, `SubagentStart`, `SubagentStop`, `Stop`, `TeammateIdle`, `TaskCompleted`,
  `PreCompact`.

**`hooks/handlers/observe.py`** dispatch table (`observe.py:146-161`) maps each hook → an
`EventEmitter` method → an event_type string emitted as one JSON line to **stdout**:

| Claude hook            | event_type string            | key `context` fields                         |
|------------------------|------------------------------|----------------------------------------------|
| SessionStart           | `session_started`            | source, transcript_path, cwd, permission_mode|
| SessionEnd             | `session_completed`*         | reason, duration_ms                          |
| UserPromptSubmit       | `user_prompt_submitted`      | prompt_preview (≤200)                        |
| PreToolUse             | `tool_execution_started`     | tool_name, tool_use_id, input_preview (≤500) |
| PostToolUse            | `tool_execution_completed`   | tool_name, tool_use_id, success, output_preview |
| PostToolUseFailure     | `tool_execution_failed`      | tool_name, tool_use_id, error                |
| PermissionRequest      | `permission_requested`       | tool_name, permission_type                   |
| Notification           | `system_notification`        | message, level                               |
| SubagentStart          | `subagent_started`           | subagent_id, agent_type                      |
| SubagentStop           | `subagent_stopped`           | subagent_id, reason                          |
| Stop                   | `agent_stopped`              | reason                                       |
| TeammateIdle           | `teammate_idle`              | teammate_id                                  |
| TaskCompleted          | `task_completed`             | task_id                                      |
| PreCompact             | `context_compacted`          | before_tokens, after_tokens                  |

`*` note the emitter emits `session_completed` while the collector enum canonical name is
`session_ended` — see §6 vocab-skew caveat.

`session_id` discovery (`observe.py:176`, fallback `observe.py:31`): JSON stdin field
`session_id`, else env `CLAUDE_SESSION_ID`, else `"unknown"`. **No execution_id / phase_id** is
known at this layer.

### 1b. Real git hooks — `hooks/git/{post-commit,pre-push,post-merge,post-rewrite,post-checkout}`

Each reads `CLAUDE_SESSION_ID` → fallback `AEF_SESSION_ID` → `"unknown"`, builds
`EventEmitter(session_id=…, provider="claude", output=sys.stderr)`, and prints **one JSON line to
stderr** (ADR-043: stderr is merged into the docker-exec stream — this is how they reach Route B).

| Hook         | event_type     | context (operation/…)        | metadata                                                        |
|--------------|----------------|------------------------------|-----------------------------------------------------------------|
| post-commit  | `git_commit`   | commit; message≤200, sha, branch | repo, files_changed, insertions, deletions, author, estimated_tokens_added/removed (chars//4) |
| pre-push     | `git_push`     | push; remote, branch         | remote_url, commits_count, commit_range (`{upstream}..HEAD`)    |
| post-merge   | `git_merge`    | merge; branch, sha           | commits_merged, is_squash                                       |
| post-rewrite | `git_rewrite`  | rebase\|amend                | mappings[{old_sha,new_sha}], commits_folded                     |
| post-checkout| `git_checkout` | clone\|checkout; is_clone, branch, prev_branch, sha | repo                                     |

- `post-commit:41-94`, `pre-push:28-51`, `post-merge:24-46`, `post-rewrite:19-36`,
  `post-checkout:36-61`.
- `hooks/git/install.py:22` installs `post-commit, post-merge, post-rewrite, pre-push` into
  `.git/hooks/` (or `--global` → `$XDG_CONFIG_HOME/git/hooks`), idempotent via the `agentic_events`
  marker string; `--uninstall` removes them.

### 1c. The emitter (shared envelope)

`lib/agentic-primitives/lib/python/agentic_events/agentic_events/emitter.py:51-79` — every event is:

```json
{
  "event_type": "<EventType value>",
  "timestamp": "<ISO-8601 UTC>",
  "session_id": "<id or 'unknown'>",
  "provider": "claude",
  "context":  { /* operation-specific */ },
  "metadata": { /* optional supplementary */ }
}
```

The canonical event_type vocabulary is `agentic_events/types.py:18-59` (session/tool/git strings
above). **This envelope is the on-the-wire contract** — anything Route A/B parses keys off
`event_type` + `session_id` + `timestamp` and stuffs the rest into `data`.

---

## 2. Collector `/events` JSONL ingestion (Route A)

Package `packages/syn-collector`.

### 2a. Endpoint + payload schema

- `collector/routes.py:107` — `@app.post("/events", response_model=BatchResponse)`,
  `async def receive_events(batch: EventBatch)`.
- Request `EventBatch` (`events/types.py:155-172`): `agent_id: str`, `batch_id: str`,
  `events: list[CollectedEvent]`.
- `CollectedEvent` (`events/types.py:127-151`):
  - `event_id: str` (16–64 chars, deterministic dedup key)
  - `event_type: EventType` (enum)
  - `session_id: str`
  - `timestamp: datetime`
  - `data: dict[str, Any]` (default `{}`)
- Response `BatchResponse` (`events/types.py:175-188`): `accepted: int`, `duplicates: int`,
  `batch_id: str`.

### 2b. Flow: dedup → store → buffer → COPY

1. `routes.py:114` — `if dedup.is_duplicate(event.event_id): duplicates += 1; continue`
   (`collector/dedup.py`: LRU OrderedDict + lock, cap 100k, O(1), atomic check-and-mark).
2. `routes.py:119` — `await store.write_event(event)` → `accepted += 1` (errors logged, loop
   continues, `routes.py:121-130`).
3. `collector/store.py:36-55` `_event_to_dict` flattens to the dict `AgentEvent.from_dict` expects:
   spreads `event.data`, then overlays reserved keys `event_type=event.event_type.value`,
   `session_id`, `timestamp=isoformat()`, `event_id`. (`event_id` therefore survives **inside the
   `data` JSONB**, not as its own column.)
4. `store.py:83-88` `write_event` → `EventBuffer.add(dict)` (flush at 1000 rows or every 0.1s).

### 2c. The `agent_events` table + exact INSERT

Schema (`packages/syn-adapters/src/syn_adapters/events/schema.py:67-86`; mirrored in migration
`projection_stores/migrations/002_agent_events.sql`, and asserted by
`events/models.py:267-274` `EXPECTED_COLUMNS`):

```sql
CREATE TABLE IF NOT EXISTS agent_events (
    time         TIMESTAMPTZ NOT NULL,
    event_type   TEXT        NOT NULL,
    session_id   TEXT        NOT NULL,
    execution_id TEXT,
    phase_id     TEXT,
    data         JSONB       NOT NULL
);
SELECT create_hypertable('agent_events','time', if_not_exists => TRUE,
                         chunk_time_interval => INTERVAL '1 day');
-- idx_events_session(session_id,time DESC), idx_events_execution(execution_id,time DESC),
-- idx_events_type(event_type,time DESC)
```

Single-row insert (`syn_adapters/events/store_write.py:73-85`):

```sql
INSERT INTO agent_events
  (time, event_type, session_id, execution_id, phase_id, data)
VALUES ($1, $2, $3, $4, $5, $6)
```

Batch path (`store_write.py:117-122`): `conn.copy_to_table("agent_events",
columns=["time","event_type","session_id","execution_id","phase_id","data"], format="text")`.

### 2d. How the 6 columns get populated

`AgentEvent.from_dict` (`events/models.py:226-262`) is the universal normalizer for **both routes**:
- `time` ← `data["time"] or data["timestamp"] or datetime.now()` (`models.py:240`).
- `event_type` ← `data["event_type"] or data["type"]`, then `_resolve_event_type` normalizes Claude
  CLI raw types (`models.py:241-242`, `233-238`): `tool_use→tool_execution_started`,
  `tool_result→tool_execution_completed`, `system.init/system→session_started`,
  `result→session_completed`, `assistant/user→token_usage`.
- `session_id` / `execution_id` / `phase_id` ← only set **if present** in the incoming dict
  (`models.py:258-260`). Validated by `field_validator(..., mode="before")` (`models.py:192`).
- `data` ← all remaining (non-reserved) keys (`models.py:245`); nested tool content is hoisted via
  `_extract_tool_data` (`models.py:248-250`).
- `to_insert_tuple` (`models.py:214-223`) → `(time, event_type, session_id, execution_id, phase_id,
  json.dumps(data))`.

**Critical:** `execution_id` and `phase_id` are NEVER set by Claude hooks/OTLP/watcher. They are
populated only when the **orchestrator** (Route B / its own correlation) injects them, or are left
NULL. Session is the only correlation key the Claude-emitted events carry.

### 2e. Full `EventType` enum (`events/types.py:18-125`)

Session: `session_started, session_ended, agent_stopped, subagent_started, subagent_stopped`.
Tool: `tool_execution_started, tool_execution_completed, tool_blocked`.
User/notify: `user_prompt_submitted, notification_sent`. Tokens: `token_usage`. Context:
`pre_compact`. Git (current): `git_commit, git_push, git_merge, git_rewrite, git_checkout,
git_branch_changed, git_operation`. Git (legacy aliases): `git_branch_created, git_branch_switched,
git_merge_completed, git_commits_rewritten, git_push_started, git_push_completed`. Workspace:
`workspace_creating/created/command_executed/destroying/destroyed/error`. Cost: `cost_recorded,
session_cost_finalized`. OTLP-sourced: `otlp_log, api_request, api_error, otlp_session_count,
otlp_commit_count`.

---

## 3. Native OTLP channel (`collector/otlp.py`, `/v1/metrics` + `/v1/logs`)

Activated by Claude Code itself when `CLAUDE_CODE_ENABLE_TELEMETRY=1` (see §5).

- Routes (`routes.py:83-91`): `POST /v1/metrics` and `POST /v1/logs`, both **JSON** OTLP wire
  format (`request.json()`), handled by `_ingest_otlp(request, parse_otlp_*, …)`. Parsed
  `CollectedEvent`s go through the **same dedup+store path** as `/events` (`routes.py:60-91`,
  `_write_deduped` at `routes.py:28`).
- Metric → EventType (the **dict at `otlp.py:54-59` is authoritative**; the top-of-file docstring
  `otlp.py:9-12` is stale and disagrees — trust the dict):
  - `claude_code.token.usage` → `TOKEN_USAGE`
  - `claude_code.cost.usage` → `COST_RECORDED`
  - `claude_code.session.count` → `OTLP_SESSION_COUNT`
  - `claude_code.commit.count` → `OTLP_COMMIT_COUNT`
- Log event.name → EventType (`otlp.py:62-67`): `claude_code.api_request→API_REQUEST`,
  `claude_code.api_error→API_ERROR`, `claude_code.tool_result→TOOL_EXECUTION_COMPLETED`,
  `claude_code.user_prompt→USER_PROMPT_SUBMITTED`; unknown → `OTLP_LOG`
  (`otlp.py:213`, bounded to 50 attrs ×500 chars, `otlp.py:223-224`).
- Output `CollectedEvent.data` carries `{"source":"otlp", "metric_name"/"model"/"cost_usd"/
  "duration_ms"/value/…}` (`otlp.py:114-140`, `193-239`).
- `session_id` ← OTLP `resource.attributes[key="session.id"].stringValue`, fallback `"unknown"`
  (`otlp.py:81-86`). **No execution_id/phase_id extracted.**
- **What OTLP ADDS over `/events`:** the only source of **per-API-call cost (`cost_usd`)**,
  fine-grained **token breakdown (input/output/cache)** per call, **API latency/error/retry**
  telemetry, and session/commit counters. The hook+transcript channel has no per-call cost and only
  per-message token totals.

---

## 4. Session-log / transcript ingestion (the watcher → Route A)

`packages/syn-collector/src/syn_collector/watcher_runner.py` + `watcher/*.py`. Runs two concurrent
tailers, both `.watch(from_end=True)`, batching into the collector's `EventCollectorClient` →
`POST /events` (`watcher_runner.py:89-112`):

1. **HookWatcher** (`watcher/hooks.py`) tails `.agentic/analytics/events.jsonl` — the JSONL the
   observe.py/git hooks wrote. `watcher/hook_parser.py:18-102` maps ~25 hook strings (incl.
   legacy/`*-start`/`*-stop` aliases) → `EventType`, requires `session_id`, parses ISO timestamp,
   computes a deterministic `event_id`.
2. **TranscriptWatcher** (`watcher/transcript.py`) recursively tails `~/.claude/projects/**/*.jsonl`
   — **Claude CLI's native session transcripts**. `watcher/transcript_parser.py:21-72` processes
   only `type:"assistant"` messages **with a `.message.usage` block**, emits exactly one
   **`TOKEN_USAGE`** event per message with `{message_uuid, input_tokens, output_tokens,
   cache_creation_input_tokens, cache_read_input_tokens}`. session_id ← `data.sessionId`, else
   override, else file-stem if >8 chars (`transcript_parser.py:50,75-87`).

Position/inode tracking + rotation detection in `watcher/base.py:115-156`; deterministic event_ids
in `watcher/event_id.py:54-102` make file re-reads idempotent against the dedup filter.
**This is genuine Claude session-log ingestion** — it hardcodes the `~/.claude/projects/**/*.jsonl`
layout and the `{type, message:{usage}, sessionId, uuid}` transcript shape.

---

## 5. How the workspace is wired to EMIT

### 5a. Container build/boot (Claude-cli provider)

`lib/agentic-primitives/providers/workspaces/claude-cli/`:
- `Dockerfile:182-185` bakes `plugins/` (incl. observability) into `/opt/agentic/plugins`;
  `Dockerfile:141` installs the `agentic_events` wheels into `/opt/venv`; `Dockerfile:216` sets
  `AGENTIC_PLUGINS_DIR=/opt/agentic/plugins`. `Dockerfile:31` documents "events emitted as JSONL to
  stderr, captured by the agent runner". **Telemetry env vars are NOT baked in** — injected at run.
- `manifest.yaml:28` `otel_native: true`; `:36-38` plugins `sdlc/workspace/observability`;
  `:64` `otel_enabled: true`.
- `scripts/entrypoint.sh:67-92` plugin discovery → `AGENTIC_PLUGIN_FLAGS`;
  `:119-145` composes git hooks from `/opt/agentic/git-hooks/` + the observability plugin's
  `hooks/git/` into `${HOME}/.git-hooks` and `git config --global core.hooksPath` → so commits/pushes
  inside the container fire the Route-A/B hooks.

### 5b. syn-api telemetry env injection (the on-switch)

`apps/syn-api/src/syn_api/_wiring.py:81-100` `_build_workspace_telemetry_env()`:

```python
collector_url = get_settings().collector_url
if not collector_url:
    return {}                     # OTLP silently no-ops if unconfigured
return {
    ENV_CLAUDE_CODE_ENABLE_TELEMETRY: "1",
    ENV_OTEL_EXPORTER_OTLP_ENDPOINT: collector_url,
}
```

Injected at `_wiring.py:144` via `WorkspaceService.create(config=ws_config,
environment=_build_workspace_telemetry_env())`, then merged into the container env through
`workspace_backends/service/workspace_service.py:114-115,220-239` and
`workspace_lifecycle.py:79-118`. Constants in `syn_shared/env_constants.py:45-48`
(`CLAUDE_CODE_ENABLE_TELEMETRY`, `OTEL_EXPORTER_OTLP_ENDPOINT`, plus `CLAUDE_SESSION_ID`).

So the two emission channels switch on like this:
- **(a) plugin/git-hook JSONL emission** — always on (plugins baked + hooks installed by entrypoint);
  needs only `CLAUDE_SESSION_ID` (and `AEF_SESSION_ID` as fallback) for correlation.
- **(b) native Claude OTLP** — on only when `collector_url` is set, via the Claude-specific
  `CLAUDE_CODE_ENABLE_TELEMETRY=1` + generic `OTEL_EXPORTER_OTLP_ENDPOINT`.

### 5c. Route B (no collector): Claude stdout/stderr → agent_events directly

`lib/agentic-primitives/lib/python/agentic_isolation/agentic_isolation/workspace.py:259` —
`await event_store.insert(parse_event(line))` for each JSONL line off the docker-exec stream.
`syn_adapters/events/parse.py:12-33` `parse_jsonl_events` accepts both `type` and `event_type`
(normalizing `type→event_type`), skips non-event lines, → `AgentEvent.from_dict` → `EventBuffer`
(`buffer_flush.py:11`) → COPY into `agent_events`. This is the path that ingests the git hooks'
stderr JSONL and Claude CLI's own `result`/`assistant` usage lines during a workflow run.

---

## 6. Claude-SPECIFIC vs reusable

**Claude-specific (must be re-implemented per harness):**
- The 14 Claude Code lifecycle hook names + `hooks.json` matcher format, and `observe.py`'s
  reading of Claude's hook stdin JSON (`session_id`, `tool_name`, `tool_use_id`, …).
- `provider:"claude"` stamp; `CLAUDE_SESSION_ID`/`AEF_SESSION_ID` discovery.
- **OTLP metric/log names are 100% Claude-branded:** `claude_code.token.usage`,
  `claude_code.cost.usage`, `claude_code.api_request`, etc. The `_METRIC_TO_EVENT_TYPE` /
  `_LOG_EVENT_TO_EVENT_TYPE` dicts key off `claude_code.*` (`otlp.py:40-67`).
- Transcript watcher's `~/.claude/projects/**/*.jsonl` path + `{type, message.usage, sessionId,
  uuid}` shape (`transcript.py`, `transcript_parser.py`).
- `AgentEvent._resolve_event_type` raw-type aliases (`tool_use`, `system.init`, `result`, …) are
  Claude CLI stdout vocabulary (`models.py:233-242`).
- `CLAUDE_CODE_ENABLE_TELEMETRY` env name (`env_constants.py:47`).

**Reusable / harness-agnostic (the generalization surface):**
- The `agent_events` table + 6-column contract and the `EventType` enum vocabulary
  (`events/types.py`, `schema.py`).
- The collector HTTP API: `POST /events` (`EventBatch`/`CollectedEvent`), `POST /v1/metrics`,
  `POST /v1/logs`, dedup-by-`event_id`, `BatchResponse` (`routes.py`, `dedup.py`).
- `AgentEvent.from_dict` normalizer + `_event_to_dict` reserved-key flattening — any dict with
  `event_type`/`session_id`/`timestamp`/`data` lands cleanly.
- The git hooks themselves are mostly generic git plumbing; only the `provider` stamp and env names
  are Claude-flavored. The `OTEL_EXPORTER_OTLP_ENDPOINT` half of the OTLP wiring is a generic OTel
  standard.
- Route B's `parse_jsonl_events` accepts any `{event_type|type, session_id, timestamp, …}` line.

**Caveat (vocab skew to fix when generalizing):** the emitter says `session_completed` while the
collector enum says `session_ended` (`agentic_events/types.py:19` vs `events/types.py`); git events
have current+legacy aliases; OTLP docstring (`otlp.py:9-12`) contradicts its own mapping dict. An
exporter should target the **collector `EventType` enum values**, which are what the table/projections
query against (e.g. `queries.py:340` filters `tool_execution_completed`).

---

## 7. What an exporter adapter must produce to land in `agent_events`

1. **Emit the canonical envelope per event:** a JSON object with `event_type` (a string that matches
   a `syn_collector.events.types.EventType` value — e.g. `tool_execution_completed`, `token_usage`,
   `git_commit`), plus `session_id`, an ISO-8601 `timestamp`, and a free-form `data`/`context`
   payload. Everything else gets folded into the `data` JSONB.
2. **Mint a deterministic `event_id`** (stable hash of session_id + type + timestamp + content) so the
   collector's LRU dedup filter makes retries/file-re-reads idempotent — random UUIDs defeat dedup.
3. **Pick a delivery route:** either batch `CollectedEvent`s into `POST /events` as an `EventBatch`
   (`agent_id`,`batch_id`,`events[]`), OR emit JSONL to stdout/stderr for the in-orchestrator
   `parse_jsonl_events`→`AgentEvent.from_dict` path. For cost/token/latency metrics, speak OTLP-JSON
   to `/v1/metrics` + `/v1/logs` (the only channel carrying per-call `cost_usd`).
4. **Carry `session_id` as the mandatory correlation key** (NOT NULL column). `execution_id` and
   `phase_id` are optional and only honored if your orchestrator injects them — Claude's own events
   never set them, so leave them out unless you have orchestration context.
5. **Conform to the 6-column shape via `AgentEvent.from_dict`:** map your timestamp→`time`, your
   type→`event_type` (run it through / match `_resolve_event_type` aliases), keep `session_id`, and
   put all remaining fields under `data`. If those four are present and `event_type` is in the enum,
   the row inserts unchanged through both routes.
