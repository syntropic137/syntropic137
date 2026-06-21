# Obs L4 - PI harness observability surface (concrete, source-grounded)

**Date:** 2026-06-21
**Author:** research pass (read-only; cloned + read both repos, did NOT modify syntropic137)
**Question:** Map the observability surface of the "PI" coding-agent harness so we
can build an event-exporter adapter that feeds syntropic137 `agent_events`. Cover
both the canonical TS agent and the Rust reimplementation; for each find the CLI
invocation and which of the four exporter source types it offers; give an
extraction recipe per event type; note the ntm flag and billing model; and show
how PI slots into the L5 `HarnessExporter` pattern.

> This REPLACES the earlier placeholder, which (correctly for that box) could not
> identify PI from a single model-card line. PI is now identified and clonable:
> **PI = the "Pi" agent harness by earendil-works (Mario Zechner)**, npm
> `@earendil-works/pi-coding-agent`, site `pi.dev`. There are two implementations:
> the canonical TypeScript monorepo and a Rust port. Both were cloned to /tmp and
> read. They CONVERGE on an identical observability surface (see "Divergence
> verdict"). Citations are real file paths/lines in each clone.

---

## TL;DR

- **PI is observable.** It offers THREE of the four exporter source types: a
  structured JSONL stdout stream, a plugin/extension hook API, and on-disk
  session JSONL transcripts. It does NOT ship native OTLP (design only in TS, a
  JS stub in Rust). That mirrors the cross-harness pattern: OTLP is the missing
  load-bearing channel everywhere (L5 section 6).
- **One event taxonomy, two binaries.** Both implementations emit the SAME
  `AgentEvent` union (`agent_start`, `turn_start/end`, `tool_execution_start/
  update/end`, `message_*`, ...) and the SAME extension event set. A single
  syntropic adapter serves both; only the install/launch differs.
- **Binary is `pi` in BOTH.** Headless = `pi -p --mode json "<prompt>"` (JSONL
  event stream on stdout). Interactive = bare `pi` (TUI). There is also a
  long-lived `pi --mode rpc` bidirectional JSONL protocol.
- **ntm flag:** PI has none today (L4-placeholder confirmed: only
  `--cc/--cod/--gmi/--oc` exist). It should get **`--pi`** (next free, matches the
  `--oc` opencode precedent). Spawn would be `ntm spawn <org>--<repo> --pi=N`.
- **Billing is HYBRID / configurable**, not fixed Max-sub or fixed API. PI is
  multi-provider and supports BOTH subscription OAuth (Anthropic Claude Pro/Max,
  OpenAI Codex/ChatGPT, GitHub Copilot) AND metered API keys. So the model-card
  entry must be "configurable; defaults to API-billed unless an OAuth/Max login
  is used." See "Billing" below.

---

## Repos inspected

| Repo | Clone | What it is | Version seen |
|---|---|---|---|
| Canonical PI | `/tmp/pi_canon_v2` (github.com/earendil-works/pi) | TS monorepo: `pi-ai` (multi-provider LLM API), `pi-agent-core` (runtime), `pi-coding-agent` (the `pi` CLI), `pi-tui` | `@earendil-works/pi-coding-agent` 0.79.9 |
| Rust PI | `/tmp/pi_rust_v2` (github.com/Dicklesworthstone/pi_agent_rust) | Single-binary Rust port, "drop-in for Pi / OpenClaw", curl-installed | `pi_agent_rust` 0.1.20 |

---

## Surface inventory - CANONICAL PI (TypeScript)

**Binary / invocation.** `pi` (`packages/coding-agent/package.json` `bin.pi =
dist/cli.js`). Hand-rolled arg parser at `packages/coding-agent/src/cli/args.ts`.
Mode resolution `packages/coding-agent/src/main.ts:98-110`
(`type Mode = "text" | "json" | "rpc"`, `args.ts:9`):

- Interactive TUI: default when stdin+stdout are TTYs and no `--print`/`--mode`.
- Headless one-shot text: `pi -p "<prompt>"` / `--print` (`args.ts:135-141`); also
  auto-selected when stdin or stdout is not a TTY (`main.ts:105`).
- Headless one-shot JSONL stream: `pi --mode json "<prompt>"` -> full event stream
  as JSONL on stdout (`packages/coding-agent/src/modes/print-mode.ts:184-196`).
- Long-lived bidirectional JSONL: `pi --mode rpc`
  (`packages/coding-agent/src/modes/rpc/rpc-mode.ts`; typed protocol in
  `rpc-types.ts`, incl. `get_session_stats -> SessionStats`).
- Exporter-friendly flags: `--session-id <id>` (deterministic id), `--session-dir
  <dir>`, `--no-session`, `--tools read,grep,ls` (read-only), `--model
  provider/id:thinking`.

**Source types:**

1. **Structured stdout stream - YES (primary headless).** `--mode json` subscribes
   to the live session stream and writes `JSON.stringify(event)\n` per event
   (`print-mode.ts:184-188`); first line is the session header via
   `session.sessionManager.getHeader()` (`print-mode.ts:191-196`). Event union
   `AgentSessionEvent` (`packages/coding-agent/src/core/agent-session.ts:125-150`)
   wrapping `AgentEvent` (`packages/agent/src/types.ts:408-423`). `type` values:
   `agent_start`, `agent_end`, `turn_start`, `turn_end`, `message_start`,
   `message_update`, `message_end`, `tool_execution_start`,
   `tool_execution_update`, `tool_execution_end`, plus session-level
   `queue_update`, `compaction_start/end`, `session_info_changed`,
   `thinking_level_changed`, `auto_retry_start/end`.
2. **Plugin / hook / extension API - YES (richest).** TS extensions auto-discovered
   from `~/.pi/agent/extensions/` (global) or `.pi/extensions/` (project) or `pi -e
   ./file.ts`. API `packages/coding-agent/src/core/extensions/types.ts`
   (`ExtensionAPI`); register with `pi.on("<event>", handler)`. Observable events
   (cited lines in `extensions/types.ts`): `session_start`(547),
   `session_shutdown`(586), `before_agent_start`(658), `agent_start`(671),
   `agent_end`(676), `turn_start`(682), `turn_end`(689), `message_start/update/
   end`(697/703/710), `tool_execution_start`(716: `toolCallId,toolName,args`),
   `tool_execution_update`(724), `tool_execution_end`(733: `toolCallId,toolName,
   result,isError`), `tool_call`(807, pre, blockable), `tool_result`(868, post,
   mutable), `before_provider_request`(645), `after_provider_response`(651).
   Skeleton examples in `packages/coding-agent/examples/extensions/` (`notify.ts`,
   `event-bus.ts`, `rpc-demo.ts`).
3. **Native OTLP - NO (design only).** `packages/agent/docs/observability.md`
   describes a `traceOperation()` / `subscribePiObservability()` /
   `diagnostics_channel("pi.observability")` contract with span names
   `pi.agent.prompt`, `pi.ai.provider.request`, `pi.agent.tool_call`. None
   implemented (grep for `traceOperation`/`@opentelemetry`/`OTEL_` = 0 hits in
   src). `packages/coding-agent/src/core/telemetry.ts` is INSTALL telemetry
   (`PI_TELEMETRY` boolean gate), not agent tracing.
4. **Session / transcript files - YES (JSONL).** Append-only JSONL via
   `packages/agent/src/harness/session/jsonl-storage.ts`. Dir `~/.pi/agent/
   sessions/` (`packages/coding-agent/src/config.ts:545-547`, `getAgentDir()` =
   `~/.pi/agent`, `:501-507`); override `PI_CODING_AGENT_SESSION_DIR` /
   `--session-dir`. Line 1 = `{type:"session",version:3,id,timestamp,cwd,
   parentSession?}` (`jsonl-storage.ts:8-15`); subsequent lines = `SessionTreeEntry`
   union (`packages/agent/src/harness/types.ts:334-420`): `message` (wraps full
   `AgentMessage`, assistant carries `usage`), `model_change`, `compaction`, etc.
   Tree-structured (each entry has `id`/`parentId`) to support fork/branch.

**Tokens/cost source.** `Usage` `packages/ai/src/types.ts:283-298`:
`{input, output, cacheRead, cacheWrite, cacheWrite1h?, totalTokens, cost:{input,
output, cacheRead, cacheWrite, total}}`. Attached PER-TURN to
`AssistantMessage.usage` (`types.ts:317`). No separate reasoning field (thinking
folds into `output`). Cost = `calculateCost(model, usage)`
(`packages/ai/src/models.ts:39-49`) from per-model `$/million` tables
(`models.generated.ts`, override `~/.pi/agent/models.json`) - a LIST-PRICE
estimate, not real subscription spend. Cumulative totals = `SessionStats`
(`packages/coding-agent/src/core/agent-session.ts:222-239`, computed
`:2935-2978`), reachable via RPC `get_session_stats`.

---

## Surface inventory - RUST PI (pi_agent_rust)

**Binary / invocation.** `pi` (`Cargo.toml` `[[bin]] name="pi", path="src/main.rs"`,
feature `tui`). Clap-derive args in `src/cli.rs`.

- Headless: `-p/--print` (`src/cli.rs:395`) + `--mode text|json|rpc`
  (`src/cli.rs:391`). Print-mode gate `src/main.rs:1330`; handler
  `run_print_mode()` `src/main.rs:6515`.
  - `pi -p --mode json "<prompt>"` -> `SessionHeader` line then one JSON
    `AgentEvent` per line (`src/main.rs:6535`, `:6559-6562`,
    `emit_json_event()` `:6809`). stdin piping supported.
- RPC: `pi --mode rpc` or `--rpc` (`src/cli.rs:399`), protocol `docs/rpc.md`
  (adds `text_delta`/`thinking_delta` and a `get_state` command returning model +
  settings + token usage).
- ACP (Zed): `pi --acp` (`src/cli.rs:404`, `src/acp.rs`) - JSON-RPC 2.0.
- Interactive TUI: bare `pi` (`src/interactive/`, `src/tui.rs`); `pi -c` continue,
  `pi -r` resume.
- **Drop-in scope caveat:** this is a drop-in for **Pi / OpenClaw, NOT Claude
  Code.** There is NO `--output-format stream-json` / Claude `--print` flag
  (`grep stream-json`/`output-format` in `src/cli.rs`/`src/main.rs` = 0). Use
  `-p --mode json`.

**Source types:**

1. **Structured stdout stream - YES (primary).** `enum AgentEvent`
   `src/agent.rs:935` with `#[serde(tag="type", rename_all="snake_case")]`.
   Variants/tags: `agent_start`(`sessionId`), `agent_end`(`sessionId,messages,
   error?`), `turn_start`(`sessionId,turnIndex,timestamp`),
   `turn_end`(`sessionId,turnIndex,message,toolResults,latencyBreakdown?`),
   `message_start/update/end`, `tool_execution_start`(`toolCallId,toolName,args`),
   `tool_execution_update`, `tool_execution_end`(`toolCallId,toolName,result,
   isError`), `auto_compaction_start/end`, `auto_retry_start/end`,
   `extension_error`. `SessionHeader` (first line) `src/session.rs:3939`:
   `type,version?,id,timestamp,cwd,provider?,model_id?,thinking_level?,leafId?,
   branchedFrom?`. (Inner fields camelCase via serde rename.)
2. **Plugin / hook / extension API - YES (WASM component model).** WIT interface
   `docs/wit/extension.wit` (`package pi:extension`): `init`, `handle-tool`,
   `handle-slash`, **`handle-event(event-json)`**, `shutdown`; host surface
   `host.call(name,input-json)`. Events to `handle-event` = `enum ExtensionEvent`
   `src/extension_events.rs:23` (names `event_name()` `:105`): `startup`,
   `agent_start`, `agent_end`, `turn_start`, `turn_end`, `tool_call`(pre,
   blockable via `ToolCallEventResult.block`), `tool_result`(post, mutable),
   `session_before_switch`, `session_before_fork`, `input`. Load with `pi -e
   <file.js>` (`src/cli.rs:425`) or `.pi/extensions`. Schema
   `docs/schema/extension_protocol.json`; arch `docs/extension-architecture.md`.
3. **Native OTLP - NO.** `Cargo.toml` has only `tracing` + `tracing-subscriber`
   (lines 215-216); no `opentelemetry`/`tracing-opentelemetry`/otlp exporter. The
   `@opentelemetry` hits (`src/extensions_js.rs:14572-14693`,
   `src/extension_preflight.rs:406`) are JS stub shims FOR extensions, not a host
   exporter. Internal `tracing` logs only (`RUST_LOG`).
4. **Session / transcript files - YES.** Path `~/.pi/agent/sessions/<encoded-
   project>/YYYY-MM-DDTHH-MM-SS.sssZ_<id>.jsonl` (`docs/session.md:13-16`). Dir
   `Config::sessions_dir()` -> `global_dir()` + `sessions` (`src/config.rs:393,
   1040`; `.pi` name `:389,1033`); override **`PI_SESSIONS_DIR`** (`:1044`) or
   `--session-dir`. V1 JSONL = `SessionHeader` line + `SessionEntry` lines
   (`message`/`model_change`/`compaction`/...), tree-structured. A segmented V2
   store (`<id>.v2/`, contract `docs/schema/session_store_v2_contract.json`,
   `src/session_store_v2.rs`) and a SQLite index (`src/session_sqlite.rs`) also
   exist; prefer V1 JSONL as the simple passive source.

**Tokens/cost source.** `struct Usage` `src/model.rs:218`:
`input,output,cache_read,cache_write,total_tokens (u64), cost: Cost`. `Cost`
camelCase: `input,output,cache_read,cache_write,total (f64 $)`. Lives on
`AssistantMessage.usage` (`src/model.rs:59`, field 64), embedded in
`turn_end.message`, `message_end.message`, `agent_end.messages`. Per-turn usage =
`turn_end.message.usage`; cumulative = sum across turns or RPC `get_state`. Cost
computed host-side from `ModelCost` per-million rates (`src/provider.rs:204-224`).
No separate `reasoning_tokens`/`prompt_tokens` on canonical `Usage`; provider
structs map onto the four (e.g. `azure.rs:777` `prompt_tokens -> usage.input`).

---

## Divergence verdict - which to target

**They do not meaningfully diverge on the observability surface.** Same binary
name (`pi`), same headless invocation (`pi -p --mode json`), same `AgentEvent`
union, same `tool_execution_*` pairing key (`toolCallId`), same extension event
set, same `~/.pi/agent/sessions/*.jsonl` transcript shape, same per-turn `Usage`
on `AssistantMessage`. A single syntropic adapter parses both byte-for-byte
(the Rust serde tags and the TS `type` strings match).

Where they differ is install/runtime, not telemetry:

| Axis | Canonical (TS) | Rust |
|---|---|---|
| Install | `npm i -g @earendil-works/pi-coding-agent` | `curl -fsSL .../install.sh \| bash` (single binary) |
| Startup / footprint | Node runtime | native, fast-start, single binary |
| OTLP design | documented (`observability.md`), unbuilt | absent (JS stub only) |
| Extension runtime | TS modules in-process | WASM component model (WIT) |
| Drop-in target | n/a (it IS Pi) | Pi / OpenClaw drop-in |

**Recommendation:** target **pi_agent_rust as the runtime/install on this VPS**
(single curl-installed binary, fast start, matches the operator's existing
Dicklesworthstone tooling: UBS, beads_rust), and treat the **canonical
earendil-works repo as the schema source of truth** (it owns the event/extension
contract the Rust port mirrors; `packages/agent/docs/hooks.md` and
`observability.md` are the design references). Because the surface is identical,
the adapter is written ONCE against the shared taxonomy and works for either
binary; only the launcher (npm `pi` vs curl `pi`) and `capabilities()` probe
differ. Pin the adapter with a captured-fixture conformance test per binary
version (L5 risk #5) since serde/TS field renames are the only realistic skew.

---

## Extraction recipe per event type

These map PI-native signals to the L5 canonical envelope (section 1.1) using the
**collector enum values** (L5 section 1.2), not PI's raw strings. PI carries only
`session_id`; the orchestrator injects `execution_id`/`phase_id` (L5 section 1.5).

### Session lifecycle -> `session_started` / `session_ended`

- **session_id:** `SessionHeader.id` (first JSONL line on stdout; on disk it is
  the filename `<id>` + header line). Settable deterministically: canonical
  `--session-id <id>`, Rust `--session <path>`/`--session-dir`. This lets the
  workspace PRE-correlate to our aggregate id at spawn time (the same advantage
  L5 notes for Gemini's `--session-id`).
- **start:** `agent_start` event (carries `sessionId`) OR the header line OR
  extension `session_start`/`startup`. `data` <- `provider`, `model`(=header
  `model_id`), `cwd`(header). Stamp receipt time (stream lines after the header
  carry no own timestamp except `turn_start.timestamp`).
- **end:** `agent_end` (carries final `messages`, `error?`) -> `session_ended`,
  `data.reason` = ok/error from `error?`; or extension `session_shutdown`. For a
  one-shot `-p` run, process exit is the end-of-session signal. `exit_code` from
  the wrapped process.

### Tool / command lifecycle -> `tool_execution_started` / `tool_execution_completed`

- **start:** `tool_execution_start` -> `data.tool_name` = `toolName`,
  `data.tool_use_id` = `toolCallId`, `data.input_preview` = redacted `args`.
- **complete:** `tool_execution_end` -> `tool_name`, `tool_use_id` = `toolCallId`,
  `data.success` = `!isError`, `data.output_preview` = redacted `result`.
- **pairing:** by `toolCallId` (stable across start/update/end in BOTH repos).
- **duration:** events carry no own duration; diff receipt timestamps of start vs
  end (or use Rust `turn_end.latencyBreakdown` for per-turn timing). Built-in tool
  names: `read,bash,edit,write,grep,find,ls`.
- **richer path:** the extension API `tool_call`(pre)+`tool_result`(post) expose
  typed per-tool `input`/`details`/`content`; use it when running the in-process
  exporter rather than the raw stream.

### Tokens / cost -> `token_usage` (+ optional `cost_recorded`)

- **source:** per-turn `AssistantMessage.usage` off `turn_end.message` /
  `message_end.message` (live), or each on-disk `message` entry (backfill), or
  cumulative via RPC (`get_session_stats` TS / `get_state` Rust).
- **normalize into the L5 token vocabulary (section 1.4):**

  | L5 canonical `data` key | PI `Usage` field (both repos) |
  |---|---|
  | `input_tokens` | `input` |
  | `output_tokens` | `output` (reasoning/thinking folded in; no separate field) |
  | `cache_read` | `cacheRead` / `cache_read` |
  | `cache_creation` | `cacheWrite` / `cache_write` |
  | `reasoning` | (none - leave absent) |
  | `total` | `totalTokens` / `total_tokens` |
  | `model` | header `model_id` / `model_change` entry |

- **per_turn flag:** PI `usage` is PER-TURN (per provider response). Set
  `data.per_turn=true` and do NOT also sum the RPC cumulative total, or you double
  count on resume/compaction (the L5 1.4 trap).
- **cost:** PI computes a list-price `cost` from a local per-model `$/million`
  table. Treat it as OPTIONAL/notional (emit `cost_recorded` only if you trust the
  table); for subscription/OAuth users it is not real spend. Prefer the L5
  approach: carry normalized tokens and price downstream from one owned pricing
  table (L5 open risk #6).

### Redaction (L5 risk, honor it)

`args`/`result` and assistant `message` bodies in the stream and the on-disk
transcript carry full prompts/outputs. Preview-truncate (the `<=200` convention,
L5 section 1.3) and never ship `~/.pi/agent/auth.json` (credential store:
canonical `packages/coding-agent/src/core/auth-storage.ts:59`; Rust
`src/auth.rs`).

---

## Billing model + ntm flag (for the model card)

- **Billing = HYBRID / configurable, multi-provider.** Both repos support
  subscription OAuth AND metered API keys:
  - OAuth/subscription: Anthropic Claude Pro/Max (canonical
    `packages/ai/src/utils/oauth/anthropic.ts`, authorize `claude.ai/oauth/
    authorize`, scopes `user:inference user:sessions:claude_code`, sends Claude
    Code identity headers `packages/ai/src/providers/anthropic.ts:867-878`; Rust
    `src/auth.rs:20-25`), OpenAI Codex/ChatGPT (`oauth/openai`-codex /
    `src/auth.rs:28-33`), GitHub Copilot, plus Gemini-CLI/Antigravity OAuth in
    Rust (`src/auth.rs:36-50`).
  - API keys: `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`GEMINI_API_KEY`/... or
    `--api-key`. Canonical default provider is `google`; ~28 providers in
    `KnownProvider` (`packages/ai/src/types.ts:23-58`). Rust: 10 native provider
    modules `src/providers/` + OpenAI-compatible presets.
  - Credentials at `~/.pi/agent/auth.json` (`ApiKeyCredential | OAuthCredential`).
- **Model-card wording:** PI is NOT cleanly "Max-sub" or "API-billed"; it is
  **configurable - defaults to API/per-token (e.g. Gemini/OpenAI key) unless the
  operator runs an OAuth login**, in which case it rides that subscription
  (Claude Max, Codex, Copilot). Route quota accordingly per the auth chosen at
  spawn. Token counts are always accurate; the dollar `cost` field is a list-price
  estimate only.
- **ntm flag:** none exists (confirmed `--cc/--cod/--gmi/--oc` only). PI should get
  **`--pi`** (next free slot, mirrors the reserved `--oc` for opencode). Spawn:
  `ntm spawn <org>--<repo> --pi=N[:model[:effort]]`. The launcher runs the `pi`
  binary; for orchestrated/observed runs it wraps `pi -p --mode json` and pipes
  stdout to the exporter (section below).

---

## How PI slots into the L5 HarnessExporter pattern

(Read against L5 section 2, esp. 2.1 the interface, 2.5 the general adapter, 2.6
the preference order.)

PI is exactly the "general adapter" case of L5 section 2.5, now de-blocked: the
5-point onboarding checklist is fully answerable, so PI graduates from
"placeholder, no adapter" to a concrete `HarnessExporter`.

1. **`capabilities()` ->** `{STRUCTURED_STREAM, HOOKS, SESSION_LOG}` for both
   binaries; `OTLP=false` (design-only TS / stub Rust). The Rust HOOKS surface is
   WASM/WIT, the TS HOOKS surface is in-process TS modules - the probe records
   which, but `normalize()` does not care.

2. **Surface selection (L5 2.6 order).** PI has no OTLP, so the order resolves to:
   **(2) structured stream** `pi -p --mode json` for orchestrated/headless runs
   -> **(3) hooks** (drop a PI extension subscribing to `agent_*`/`turn_*`/
   `tool_call`/`tool_result`) for in-process lifecycle -> **(4) session-log tail**
   `~/.pi/agent/sessions/**/*.jsonl` for interactive + backfill. The interactive
   composite (L5 section 5.2) = capture-pane lifecycle + session-log tail for
   tokens/tools, since the TUI pane does not surface `usage`.

3. **`session_id(raw)` ->** `SessionHeader.id`. PI uniquely lets us PIN it at spawn
   (`--session-id`/`--session`), so PI is in the easy-correlation tier with Gemini,
   not the after-the-fact-join tier (Codex). Still, per L5 1.5 the adapter only
   sets `session_id`; the `ExporterRunner` injects `execution_id`/`phase_id`.

4. **`normalize(raw)` ->** the recipe above. `raw` is a JSONL line from `--mode
   json`, an `ExtensionEvent` JSON from `handle-event`, OR a `SessionEntry` from
   the transcript - all three feed the SAME `normalize()` and yield the same
   `CanonicalEvent` envelope (L5 section 5.3: one adapter shape, many `RawSignal`
   sources). Emits collector enum values (`session_started`, `session_ended`,
   `tool_execution_started`, `tool_execution_completed`, `token_usage`).

5. **`event_id(ev)` ->** deterministic hash of `session_id + type + timestamp +
   `toolCallId`/content`. `toolCallId` makes tool-pair dedup clean.

6. **Registry seam (L5 section 4.1).** Add `"pi": PiExporter` to the `_EXPORTERS`
   registry beside `_ADAPTERS`, dispatched by the same agent name the new `--pi`
   ntm flag selects. The `ExporterRunner` owns route selection (POST `/events`
   batch; NOT OTLP - PI has none) and `context:{}` injection. Reuse the existing
   collector client (`packages/syn-adapters/.../collector/client*.py`), exactly as
   the Claude lane does. This is additive; nothing in `agent_events` /
   `AgentEvent.from_dict` / collector routes changes.

7. **Lane discipline (L5 / L4 point 5).** Telemetry to the collector only, never
   through aggregates; the adapter is pure extraction+mapping and unit-testable
   against a captured `--mode json` fixture per binary version.

**Net:** PI is a clean fit for the existing pattern and a GOOD second/third
harness to build after the proven Claude hook path (L5 Increment 0), because (a)
its structured stream is as clean as Codex `--json` but with NO post-run SQLite
join required, (b) it can pin our `session_id` like Gemini, and (c) the TS and
Rust binaries share one taxonomy so one adapter + two fixtures covers both. Its
only gap versus the OTLP-native ideal is cost/OTLP, which L5 already treats as the
optional top layer, not the floor.

---

## Citation index

Canonical (`/tmp/pi_canon_v2`, paths relative to it):
- CLI/modes: `packages/coding-agent/src/cli/args.ts:9,135-141`,
  `src/main.ts:98-110`, `src/modes/print-mode.ts:184-196`,
  `src/modes/rpc/rpc-mode.ts`, `rpc/rpc-types.ts`.
- Events: `packages/agent/src/types.ts:408-423`,
  `packages/coding-agent/src/core/agent-session.ts:125-150,222-239,2935-2978`.
- Extensions: `packages/coding-agent/src/core/extensions/types.ts:547-868`,
  `packages/agent/docs/hooks.md`, `examples/extensions/*`.
- OTLP design (unbuilt): `packages/agent/docs/observability.md`;
  install telemetry: `packages/coding-agent/src/core/telemetry.ts`.
- Sessions: `packages/agent/src/harness/session/jsonl-storage.ts:8-15`,
  `packages/agent/src/harness/types.ts:334-420`,
  `packages/coding-agent/src/config.ts:481-482,501-507,545-547`.
- Usage/cost: `packages/ai/src/types.ts:283-298,317`,
  `packages/ai/src/models.ts:39-49`.
- Auth/billing: `packages/ai/src/utils/oauth/{index.ts:42-46,anthropic.ts}`,
  `packages/ai/src/providers/anthropic.ts:867-878`,
  `packages/ai/src/env-api-keys.ts:69-71`,
  `packages/coding-agent/src/core/auth-storage.ts:59`,
  `packages/ai/src/types.ts:23-58` (KnownProvider).

Rust (`/tmp/pi_rust_v2`, paths relative to it):
- CLI/modes: `src/cli.rs:391,395,399,404,425`, `src/main.rs:1330,6515,6535,
  6559-6562,6809`, `docs/rpc.md`, `src/acp.rs`.
- Events: `src/agent.rs:935`, `src/session.rs:3939` (SessionHeader).
- Extensions: `docs/wit/extension.wit`, `src/extension_events.rs:23,105`,
  `docs/schema/extension_protocol.json`, `docs/extension-architecture.md`.
- No-OTLP: `Cargo.toml:215-216`, `src/extensions_js.rs:14572-14693`,
  `src/extension_preflight.rs:406` (JS stub).
- Sessions: `docs/session.md:13-32`, `src/config.rs:389,393,1033,1040,1044`,
  `docs/schema/session_store_v2_contract.json`, `src/session_store_v2.rs`,
  `src/session_sqlite.rs`.
- Usage/cost: `src/model.rs:59,218`, `src/provider.rs:204-224`.
- Auth/billing: `src/auth.rs:20-50`, `src/cli.rs:294,298,302`,
  `src/providers/` (10 modules), `docs/providers.md:15`.
