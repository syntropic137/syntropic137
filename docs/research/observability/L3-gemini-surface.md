# Obs L3 — Gemini CLI Observability Surface (for a syntropic137 `agent_events` exporter)

**Scope:** Map the observability surface of the **Gemini CLI** (and its successor,
**Antigravity CLI**) so we can build an event-exporter adapter that lands cost/tokens,
session lifecycle, and tool actions into syntropic137 `agent_sessions` / `agent_events`.

**Investigated on this box (VPS), 2026-06-20.**
- Binary: `/home/ubuntu/.local/bin/gemini` → wrapper → `~/.bun/bin/gemini` →
  `~/.bun/install/global/node_modules/@google/gemini-cli/bundle/gemini.js`
- **Installed version: `gemini-cli` `0.47.0`** (`package.json`)
- Install method: **bun global** (not npm `/usr/lib/node_modules`).
- Bundled vendor docs (authoritative, ship with the binary):
  `~/.bun/install/global/node_modules/@google/gemini-cli/bundle/docs/cli/{telemetry,headless,session-management,settings}.md`

> **Headline:** Gemini CLI has a **first-class, OTLP-native OpenTelemetry pipeline**
> (logs + metrics + traces, incl. token-usage metrics and OTel GenAI semantic
> conventions). This is the cleanest extraction path and is **real, not aspirational**
> — confirmed in both the bundled docs and the compiled bundle (43× `otlpEndpoint`,
> 36× `OTEL_EXPORTER_OTLP_ENDPOINT`, metric `gemini_cli.token.usage`). There are
> **three independent extraction surfaces** (OTLP, headless `--output-format`,
> on-disk session JSONL), giving us live and post-hoc options.
>
> **Migration risk:** Gemini CLI is **deprecating ~2026-06-18** for free/Pro/Ultra
> tiers in favor of **Antigravity CLI (`agy`)**. Antigravity keeps a JSONL transcript
> on disk and hooks, but **changes paths + schema**, and its **OTLP support is
> unconfirmed**. Enterprise/paid-API-key Gemini CLI continues in parallel. See §7.

---

## 1. Surface inventory

### 1.1 `~/.gemini/` layout (this box)
| Path | What it is | Obs value |
|---|---|---|
| `~/.gemini/settings.json` | Global config (hooks, telemetry, mcpServers, auth) | **Where we'd enable telemetry / register hooks** |
| `~/.gemini/tmp/<project>/chats/session-<ISO>-<short>.jsonl` | **Per-session conversation transcript (JSONL)** | **Primary post-hoc extraction** — has tokens + toolCalls |
| `~/.gemini/tmp/<project>/tool-outputs/session-<uuid>/<tool>__<id>.txt` | Raw tool stdout (large outputs spilled to file) | Full tool-result bodies |
| `~/.gemini/tmp/<project>/logs.json` | Append log of user-message events (`sessionId`,`messageId`,`type`,`message`) | Lightweight prompt log (NOT the rich stream) |
| `~/.gemini/tmp/<project>/otel/` | OTLP collector output when `target=local`+collector (per docs) | Local OTLP capture dir |
| `~/.gemini/history/<project>/` | Shell-command history per project (`.project_root` marker) | Minor |
| `~/.gemini/projects.json` | Map `cwd → projectName` | Resolve project label from path |
| `~/.gemini/state.json` | UI state (banner counts, tips) | none |
| `~/.gemini/installation_id` | Stable install UUID (`7e7187be-…`) | Correlation id (also an OTel attr `installation.id`) |
| `~/.gemini/oauth_creds.json`, `google_accounts.json` | OAuth creds (auth=`oauth-personal`) | secrets — do NOT export |
| `~/.gemini/skills/`, `~/.gemini/tmp/.../*.txt` | Agent skills, scratch | none |

`projectHash` in the JSONL is a sha256 of the project path; `~/.gemini/tmp/<project>`
uses the human project name from `projects.json`.

### 1.2 CLI flags relevant to observability (`gemini --help`, v0.47.0)
- `-p, --prompt` / `-i, --prompt-interactive` — **headless / non-interactive mode**.
- `-o, --output-format text|json|stream-json` — **structured output incl. token stats** (§4).
- `--session-id <uuid>` — **inject our own session UUID** (lets us pre-correlate to an `agent_sessions` aggregate id).
- `-r, --resume`, `--session-file`, `--list-sessions`, `--delete-session` — session lifecycle mgmt.
- `--approval-mode default|auto_edit|yolo|plan`, `-y/--yolo` — affects `tool_call.decision` telemetry.
- `--acp` (Agent Client Protocol mode) — structured agent I/O surface (alt integration path).
- No dedicated `telemetry`/`usage` subcommand; telemetry is config-driven (§3). Subcommands present: `mcp`, `extensions`, `skills`, `hooks`, `gemma`.

### 1.3 Hooks subcommand (`gemini hooks`)
- Only command: `gemini hooks migrate` (imports Claude Code hooks → Gemini). Hooks themselves
  are **defined in `settings.json`** (see live example below), not via the subcommand.
- **Live example on this box** (`~/.gemini/settings.json`) — a `BeforeTool` hook wired to `dcg`:
  ```json
  "hooks": { "BeforeTool": [ { "matcher": "run_shell_command",
    "hooks": [ { "name": "dcg", "type": "command",
                 "command": "/home/ubuntu/.local/bin/dcg", "timeout": 5000 } ] } ] }
  ```
- Hook events (Claude-Code-parity): `BeforeTool` confirmed live; the migrate path implies
  the standard `PreToolUse/PostToolUse/SessionStart/Stop`-style set. **Hooks are a viable
  side-channel** (fire a command on each tool call that POSTs to our collector), but OTLP/
  JSONL are richer and lower-maintenance.

---

## 2. Session lifecycle & on-disk session JSONL (extraction surface A — post-hoc)

**Authoritative storage path** (`docs/cli/session-management.md:18`):
`~/.gemini/tmp/<project_hash>/chats/` — one file per session,
`session-<ISO8601>-<shorthash>.jsonl`. Retention via
`general.sessionRetention` (`enabled`, `maxAge` e.g. `"30d"`; `settings.md:40-41`).

**File format = an event-log / append journal, NOT a flat array.** Lines alternate
between full message records and `{"$set": {...}}` mutation records (the CLI persists a
running snapshot). Observed line shapes (from
`~/.gemini/tmp/seshmagic/chats/session-2026-06-12T22-54-977ca606.jsonl`):

- **Header (line 0):** `{ sessionId, projectHash, startTime, lastUpdated, kind:"main" }`
- **`$set` lines:** snapshot writes (`{"$set":{"messages":[...]}}`) — dedupe against message ids.
- **`user` message:** `{ id, timestamp, type:"user", content:[{text}] }`
- **`gemini` message (the gold):**
  ```json
  { "id","timestamp","type":"gemini","model":"gemini-2.5-flash",
    "content":[{text}], "thoughts":[...],
    "tokens": { "input":25474,"output":226,"cached":0,
                "thoughts":553,"tool":0,"total":26253 },
    "toolCalls":[ ... ] }
  ```
- **`toolCalls[]` element:**
  ```json
  { "id":"update_topic__update_topic_1781304904356_0",
    "name":"update_topic",
    "args": { ... },
    "result": [ { "functionResponse": { "id","name",
                   "response": { "output": "..." } } } ],
    "status":"success",
    "timestamp":"2026-..." }
  ```

**What we can extract from the JSONL alone:** session id, model, per-assistant-turn token
breakdown (input/output/cached/thoughts/tool/total), tool name + args + result + success
status + timing, user prompts, and assistant thoughts. **No dollar cost** (tokens only).

**Tradeoffs:** rich and zero-config (always written), but it's an internal snapshot
format (the `$set` journal) that can change between versions, and tailing it live is
fiddly. Best as a **post-hoc / backfill importer**, with OTLP/stream-json as the live path.

---

## 3. OTLP-native OpenTelemetry (extraction surface B — live, RECOMMENDED)

**This is real and is the primary recommended integration.** From the bundled
`docs/cli/telemetry.md` (v0.47.0) and confirmed in the compiled bundle.

### 3.1 Config (settings.json `telemetry` block, or env vars)
| Setting | Env var | Values | Default |
|---|---|---|---|
| `telemetry.enabled` | `GEMINI_TELEMETRY_ENABLED` | bool | `false` |
| `telemetry.traces` | `GEMINI_TELEMETRY_TRACES_ENABLED` | bool | `false` |
| `telemetry.target` | `GEMINI_TELEMETRY_TARGET` | `local`/`gcp` | `local` |
| `telemetry.otlpEndpoint` | `GEMINI_TELEMETRY_OTLP_ENDPOINT` | URL | `http://localhost:4317` |
| `telemetry.otlpProtocol` | `GEMINI_TELEMETRY_OTLP_PROTOCOL` | `grpc`/`http` | `grpc` |
| `telemetry.outfile` | `GEMINI_TELEMETRY_OUTFILE` | file path (overrides endpoint) | – |
| `telemetry.logPrompts` | `GEMINI_TELEMETRY_LOG_PROMPTS` | bool | `true` |
| `telemetry.useCollector` | `GEMINI_TELEMETRY_USE_COLLECTOR` | bool | `false` |
| `GEMINI_CLI_SURFACE` | – | string | – (custom User-Agent/surface tag) |

**To point Gemini CLI at OUR collector:** set
`telemetry.enabled=true`, `target=local`, `otlpProtocol=grpc|http`,
`otlpEndpoint=http://<syn-collector>:4317` — or just env vars
`GEMINI_TELEMETRY_ENABLED=true GEMINI_TELEMETRY_OTLP_ENDPOINT=...`. The CLI then exports
**standard OTLP** (any OTel backend works), so our collector ingests it like any OTLP source.
`outfile` gives a file sink for local capture/replay instead of a live endpoint.

### 3.2 Common attributes on ALL signals
`session.id`, `installation.id`, `active_approval_mode`, `user.email` (when authed).
→ these are our correlation keys into `agent_sessions`.

### 3.3 Logs (events) — the rich semantic stream
- `gemini_cli.config` — startup config (model, mcp servers/tools counts, approval_mode,
  auth_type, output_format, worktree_active, optional GitHub Actions context).
- `gemini_cli.user_prompt` — `{prompt_length, prompt_id, prompt?, auth_type}`.
- `gemini_cli.tool_call` — **per tool call**: `function_name, function_args, duration_ms,
  success, decision("accept"/"reject"/"auto_accept"/"modify"), error?, error_type?,
  prompt_id, tool_type("native"/"mcp"), mcp_server_name?, extension_name?,
  content_length?, start_time?, end_time?, metadata{model_added_lines,…}`.
- `gemini_cli.tool_output_truncated`, `gemini_cli.edit_strategy`, `gemini_cli.edit_correction`.
- `gemini_cli.file_operation` — `{tool_name, operation(create/read/update), lines?, mimetype?, programming_language?}`.
- `gemini_cli.api_request` / `gemini_cli.api_response` — Gemini API round-trips.
- `gen_ai.client.inference.operation.details` — **OTel GenAI convention**:
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.request.model`,
  `gen_ai.provider.name`, `gen_ai.operation.name`, finish reasons, temperature/top_p/top_k/max_tokens.
- Approval-mode lifecycle: `approval_mode_switch`, `approval_mode_duration`, `plan_execution`.

### 3.4 Metrics
- **`gemini_cli.token.usage`** (Counter) — attrs `model`, `type`∈{input,output,thought,cache,tool}. **← cost/token source.**
- `gen_ai.client.token.usage` (per-operation token counts), `gen_ai.client.operation.duration`.
- `gemini_cli.session.count`, `gemini_cli.tool.call.count`, `gemini_cli.tool.call.latency`,
  `gemini_cli.tool.queue.depth`, `gemini_cli.file.operation.count`, `gemini_cli.lines.changed`,
  `gemini_cli.api.request.count`, `gemini_cli.chat_compression`, `gemini_cli.startup.duration`,
  plus onboarding/performance/overage/slash-command families
  (full list grep'd from bundle — see appendix).

### 3.5 Traces
Spans for agent/backend ops. **Detailed trace attributes (full prompts, tool outputs)
are OFF by default** — set `telemetry.traces=true` / `GEMINI_TELEMETRY_TRACES_ENABLED=true`.

> **No native dollar-cost.** Tokens are first-class; cost must be computed by us
> (tokens × per-model price). Capture `model` + token `type` breakdown and price downstream.

---

## 4. Headless `--output-format` (extraction surface C — orchestration-time)

When WE invoke Gemini CLI inside a syntropic137 workspace (the orchestration use case),
use headless structured output (`docs/cli/headless.md`):

- **`--output-format json`** → single object `{ response:string, stats:{tokens,latency}, error?:object }`.
  Easiest for one-shot: `gemini --output-format json -p "…" | jq '.stats'`.
- **`--output-format stream-json`** → **newline-delimited JSON event stream** (best for live ingest):
  - `init` — session metadata (session ID, model)
  - `message` — user/assistant message chunks
  - `tool_use` — tool call requests + args
  - `tool_result` — executed-tool output
  - `error` — non-fatal warnings/system errors
  - `result` — **final outcome w/ aggregated stats + per-model token-usage breakdown**
- **Exit codes:** `0` ok, `1` general/API error, `42` input error, `53` turn-limit exceeded.

This maps almost 1:1 onto our `agent_events` (init→SessionStarted, tool_use/tool_result→
ToolCall lifecycle, result→tokens/cost + SessionCompleted) **without parsing internal files**.
This is the natural surface because syn already "captures agent stdout (JSONL) externally"
(per AGENTS.md, `WorkflowExecutionEngine`).

---

## 5. Extraction recipe (cost / tokens · session lifecycle · tool actions)

| Need | Live (we invoke) | Live (interactive user) | Post-hoc |
|---|---|---|---|
| **Session start/end** | `stream-json` `init`/`result` events; pass `--session-id <our-uuid>` | OTLP `gemini_cli.config` + `session.id`; `gemini_cli.session.count` | JSONL header `startTime`/`lastUpdated` |
| **Tokens** | `result` event per-model token breakdown; `json` `.stats` | OTLP metric `gemini_cli.token.usage` (type=input/output/cache/thought/tool) + log `gen_ai.usage.*` | JSONL `gemini` msg `.tokens.{input,output,cached,thoughts,tool,total}` |
| **Cost** | compute from tokens×price (no native cost) | same | same |
| **Tool actions** | `tool_use`+`tool_result` events | OTLP log `gemini_cli.tool_call` (name,args,decision,success,duration,tool_type) | JSONL `toolCalls[]` (name,args,result,status) + spill files in `tool-outputs/` |
| **Prompts / model** | events carry model; prompt in `message` | `gemini_cli.user_prompt` (gated by `logPrompts`) | JSONL `content[].text`, `model` |
| **Errors** | `error` event + exit code | log `error`/`error_type` on `tool_call` | `status:"error"` on toolCalls |

**Correlation key:** `session.id` (==`--session-id` if we inject it) ties OTLP signals,
stream-json events, and the on-disk JSONL together, and maps to a syn `AgentSession` aggregate.

---

## 6. OTLP-native option — verdict: **REAL, use it as primary**

Confirmed two ways: (1) bundled vendor doc `telemetry.md` documents full config + signal
catalog; (2) compiled bundle contains the wiring (`otlpEndpoint`×43, `otlpProtocol`×36,
`OTEL_EXPORTER_OTLP_ENDPOINT`×36, `gemini_cli.token.usage`, `gen_ai.client.token.usage`).
syntropic137 already speaks event ingestion (`syn-collector`); standing up / reusing an
**OTLP receiver** lets Gemini CLI stream telemetry with zero bespoke parsing and survives
CLI version drift better than the internal JSONL snapshot format. Recommended primary surface;
keep stream-json for the orchestration path and the JSONL importer for backfill.

---

## 7. Successor: Antigravity CLI (`agy`) — migration impact

Gemini CLI is **deprecating ~2026-06-18** in favor of **Antigravity** (IDE + CLI `agy` +
SDK + server harness). **Free/Pro/Ultra tiers stop being served on that date; enterprise /
paid-API-key Gemini CLI keeps working & updating in parallel** (Google Developers Blog).
The OSS `google-gemini/gemini-cli` repo stays Apache-2.0 but is "hollow" without the backend.

**Confirmed about `agy`:**
- Headless equiv exists: `agy -p/--print/--prompt`, `--print-timeout`, `--continue`, `--conversation`.
- **On-disk JSONL transcripts** under
  `~/.gemini/antigravity-cli/brain/<conversation-id>/.system_generated/logs/`:
  `transcript.jsonl` (truncated) + `transcript_full.jsonl` (full tool results).
  **New per-line schema:** `step_index, source(USER_EXPLICIT/SYSTEM/MODEL), type, status,
  content, created_at, tool_calls[]`. Index at `…/history.jsonl`; protobuf `conversations/` store.
- **Hooks carried over** (JSON lifecycle interceptors: pre-tool / post-edit / session-start).
- **In-session token reporting**: `/usage`, `/context`, status-bar token counts; status-line
  JSON metadata (model + token usage) is pipeable.

**UNCONFIRMED (verify with a 1-hour spike on a real `agy` install):**
- **Whether `agy` actually emits OTLP** (telemetry config *appears* to mirror Gemini's
  `otlpEndpoint`/`otlpProtocol`/`outfile`, but NOT confirmed against Google docs; no hands-on
  source demonstrated OTLP emission). **Do not assume `gemini_cli.token.usage` still flows.**
- Exact config dir (`~/.gemini/antigravity-cli/` vs `~/.config/antigravity/`), JSON-output
  flag name/stability (`--output json` vs `--output-format json`, reportedly unrecognized in
  some builds), env var name, and any dollar-cost reporting (none found).

**Impact on our adapter (if built against Gemini CLI):**
- **JSONL tailer BREAKS** — path (`~/.gemini/tmp/<proj>/chats/*.jsonl` →
  `~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript*.jsonl`) and
  per-line schema both change. Re-map parser; group by conversation-id not project-hash.
- **OTLP path UNCERTAIN** — biggest risk to the recommended surface. Gate the adapter behind
  a capability probe.
- **Hooks survive** — lowest-migration-risk capture path; consider a hook fallback.
- **stream-json** orchestration path likely survives in spirit but flag/schema may differ.

**Design implication:** build a thin **CapabilityProbe + surface abstraction** so the adapter
can switch between {OTLP, stream-json, JSONL-tailer, hooks} per CLI variant/version, rather
than hard-coding Gemini-CLI internals. Prefer OTLP + stream-json (standardized) over the
internal JSONL snapshot. Run the `agy` spike before committing to OTLP for the successor.

---

## 8. Gaps / caveats
- **No native cost ($)** in any surface — compute from tokens×model price.
- **Internal JSONL is a snapshot/`$set` journal**, version-fragile; not a stable contract.
- **Trace detail off by default** (`telemetry.traces=true` needed for prompts/tool-output spans).
- **Prompt redaction:** `telemetry.logPrompts=false` strips prompt bodies — respect for PII;
  syn already clears secrets pre-exec (ADR-024), keep prompts out unless needed.
- **Secrets in `~/.gemini`** (`oauth_creds.json`) — never read/export.
- **OTLP defaults to `grpc` @ `localhost:4317`** — our collector must speak gRPC OTLP (or set `otlpProtocol=http`).
- Antigravity OTLP unconfirmed (§7) — primary surface may not survive the successor unchanged.

---

## 9. Adapter sketch (`GeminiEventExporter` → syn `agent_events`)

```
                         ┌────────────────────────────────────────────┐
   Gemini CLI run        │  syn GeminiCliObservabilityAdapter          │
 (we invoke OR user) ───▶│  surface = probe(cliVariant, version)        │
                         │   ├─ OTLP receiver  (PRIMARY, live)          │  ──▶ NormalizedAgentEvent
                         │   ├─ stream-json parser (orchestration path) │  ──▶ AgentSession aggregate
                         │   ├─ JSONL importer (backfill / post-hoc)    │  ──▶ token/cost telemetry (Lane 2)
                         │   └─ hooks shim     (fallback)               │
                         └────────────────────────────────────────────┘
```

**Recommended wiring**
1. **Live (orchestrated runs):** invoke `gemini --output-format stream-json --session-id <agentSessionId> -p "…"`.
   Map events → domain/telemetry:
   - `init`  → `AgentSessionStarted{session_id, model}` (Lane 1 fact)
   - `tool_use` → `ToolCallStarted{name,args}` ; `tool_result` → `ToolCallCompleted{output,success}` (Lane 2 trace)
   - `result` → record per-model token usage → **observability recorder** (NOT the event store, per Two-Lane rule); compute cost; emit `AgentSessionCompleted`.
   - non-zero exit / `error` → `AgentSessionFailed{exit_code}`.
2. **Live (interactive users):** enable `telemetry.enabled=true target=local otlpEndpoint=<syn-collector:4317>`;
   ingest `gemini_cli.tool_call`, `gemini_cli.token.usage`, `gen_ai.*`, keyed by `session.id`.
3. **Backfill:** sweep `~/.gemini/tmp/*/chats/*.jsonl`, fold `$set` journal → final messages,
   emit historical token/tool events. Idempotent on `(session.id, message.id, toolCall.id)`.
4. **Successor guard:** `probe()` detects `agy` (path `~/.gemini/antigravity-cli/…`,
   transcript schema `step_index/source/type`) and swaps in the Antigravity JSONL mapper;
   keep OTLP behind a runtime capability check until confirmed for `agy`.

**Field mapping crib (Gemini → syn):**
`session.id`→`agent_session_id` · `gemini_cli.token.usage{type}`→token telemetry ·
`tool_call.function_name/function_args/success/duration_ms`→ToolCall event ·
`gen_ai.usage.input_tokens/output_tokens`→prompt/completion tokens ·
`model`→model id (cost lookup) · `installation.id`→host/install correlation.

---

## Appendix — sources (paths & commands on this box)
- Binary/version: `~/.local/bin/gemini` (bash wrapper) → `~/.bun/install/global/node_modules/@google/gemini-cli/`, `package.json` version `0.47.0`.
- `gemini --help`, `gemini hooks --help` (v0.47.0 flag/subcommand inventory).
- Bundled docs: `…/bundle/docs/cli/telemetry.md` (OTLP config + full log/metric/trace catalog),
  `…/headless.md` (output formats + exit codes), `…/session-management.md:18` (JSONL storage path + retention),
  `…/settings.md` (telemetry + sessionRetention keys), `…/tutorials/automation.md` (json output usage).
- Live config: `~/.gemini/settings.json` (BeforeTool/`dcg` hook, `mcpServers`, auth=oauth-personal).
- Session sample: `~/.gemini/tmp/seshmagic/chats/session-2026-06-12T22-54-977ca606.jsonl` (tokens + toolCalls schema).
- Telemetry log sample: `~/.gemini/tmp/<project>/logs.json`; tool spill: `~/.gemini/tmp/<project>/tool-outputs/`.
- Bundle grep: `grep -roh 'gemini_cli\.[a-z_.]*' …/bundle/chunk-*.js` (metric/event name catalog);
  `otlpEndpoint`×43, `OTEL_EXPORTER_OTLP_ENDPOINT`×36 confirm OTLP wiring compiled in.
- Antigravity successor research (web, multiple sources; OTLP unconfirmed): Google Developers Blog
  "transitioning-gemini-cli-to-antigravity-cli", Gemini Code Assist deprecation doc (2026-06-18),
  Google Cloud Community "Antigravity CLI tutorial series Part 2" (brain/transcript paths),
  digitalapplied/dev.to/explainx hands-on (hooks, `/usage`, headless `agy -p`). Verify `agy` empirically.
```
