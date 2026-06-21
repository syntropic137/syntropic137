# Obs L5 v2 - Standardized Cross-Harness Observability Design (CANONICAL)

**Status:** CANONICAL. This document SUPERSEDES `obs-L5-design.md` (v1). It folds in
every correction from the cross-model review (`obs-L5-review.md`, verdict
SOUND-WITH-CHANGES) and the now-mapped PI surface (`obs-L4-pi-surface.md`). Where v1
and this document disagree, this document wins.

**Scope:** ONE harness-agnostic observability design for syntropic137, synthesizing the
Phase-1 surface maps (L1 Claude ground truth, L2 Codex, L3 Gemini, L4 PI). Design only;
no repo source was modified to produce this. All claims below were spot-checked against
live source on 2026-06-21.

**Repo:** `/data/projects/synstress` (syntropic137 + vendored `lib/agentic-primitives`).
Citations are `file:line` relative to that root.

**Design north star:** generalize the mechanism that ALREADY lands rows for Claude today
(hook + session-log + exporter into `agent_events` via `/events`), keep the messy
per-harness extraction underneath, and treat OTLP as a LATER, gated presentation layer
that is NOT yet proven to land (2026-06-18 retro). The load-bearing channel is
`/events` + `CollectedEvent`, not OTLP.

---

## 0. What changed from v1 (read this first)

The review found v1 directionally sound but overstating landability in several places.
The seven corrections below are load-bearing; the rest of this document is v1 re-expressed
around them.

1. **EVENT-VOCABULARY CONTRACT (highest-risk fix).** v1 told adapters to emit the
   `syn_collector` enum values, naming `session_ended`. That value NEVER lands: persistence
   runs through `AgentEvent.from_dict`, which is typed against `syn_shared.events`, where
   the lifecycle value is `session_completed` and `session_ended` does not exist. Adapters
   MUST validate against `syn_shared.events`, not the collector enum. See section 1.2.
2. **ORDERING.** `agent_events` has only a `time` column, no `sequence`. Codex `--json` has
   no timestamps and capture-pane events are receipt-stamped, so time ordering is unsafe.
   Add a per-source monotonic `sequence` and carry `tool_use_id`/`call_id` for start/end
   pairing. See section 1.6.
3. **TOKEN ACCOUNTING.** Store `usage_scope` and `source_of_truth`; projections dedupe or
   replace cumulative totals rather than summing. Also: match the token KEY names the
   existing projection already writes (`cache_creation_tokens`/`cache_read_tokens`), do not
   invent a third vocabulary. See section 1.4.
4. **REDACTION is a HARD requirement, not an open question.** `record_observation` strips
   only reserved keys today, not secrets. Adapters must preview, bound, and redact
   rollout/JSONL/tool-output payloads BEFORE writing. See section 1.7.
5. **ARCHITECTURE.** OTLP is downgraded to a LATER gated layer (the 2026-06-18 experiment
   left native OTLP unproven). The build starts at the orchestration stream / collector
   seam, NOT inside the interactive-tmux pane driver. See sections 3 and 4.
6. **PI is now a concrete adapter** (capabilities `{STRUCTURED_STREAM, HOOKS, SESSION_LOG}`;
   primary source `pi -p --mode json` JSONL stdout; target `earendil-works/pi`; reserve
   `--pi` ntm flag; hybrid billing). Claude/Codex/Gemini/opencode adapters are kept. See
   section 2.6.
7. **INCREMENT 0 sharpened.** Smallest shippable slice is a fixture-tested canonical-event
   normalizer that proves one batch lands in `agent_events` through the REAL accepted
   vocabulary, AND fixes the enum-vocabulary contract. Refactor the existing Claude hook
   path behind `HarnessExporter` with a no-op runner on the current `/events` route. Codex
   `exec --json` is the next harness (richest structured surface). See section 7.

---

## 1. NORMALIZED EVENT SCHEMA

### 1.1 The landing contract (the target, not a proposal)

All harnesses must produce rows that fit the existing 6-column shape
(`packages/syn-adapters/src/syn_adapters/events/schema.py:67-75`):

```sql
agent_events(
  time         TIMESTAMPTZ NOT NULL,   -- event time (adapter stamps if harness omits)
  event_type   TEXT        NOT NULL,   -- a syn_shared.events EventType VALUE (see 1.2)
  session_id   TEXT        NOT NULL,   -- the ONLY correlation key the harness carries
  execution_id TEXT,                   -- orchestrator-injected, else NULL
  phase_id     TEXT,                   -- orchestrator-injected, else NULL
  data         JSONB       NOT NULL    -- everything else (provider, model, tokens, args...)
)
```

`AgentEvent.from_dict` (`packages/syn-adapters/src/syn_adapters/events/models.py:226-262`)
is the sole normalizer. It does: `timestamp -> time` fallback, `type -> event_type`,
`_resolve_event_type` mapping, remaining keys folded into `data`, and `session_id`/
`execution_id`/`phase_id` carried only when present (`models.py:258-260`). Any adapter that
produces an envelope this function accepts lands cleanly. No schema change is needed to
onboard a new harness; that is the whole point.

### 1.2 EVENT-VOCABULARY CONTRACT (the highest-risk fix)

**Rule: every adapter's `event_type` MUST be a value accepted by `syn_shared.events`, NOT a
`syn_collector` enum value, NOT a harness-native string. Validate against
`syn_shared.events`, because persistence runs through `AgentEvent.from_dict`, which is typed
against `syn_shared.events`.**

The two enums are divergent, and the divergence silently drops rows:

- `syn_shared.events` is the SINGLE SOURCE OF TRUTH for persisted event names
  (`packages/syn-shared/src/syn_shared/events/__init__.py:1-10`). It defines
  `SESSION_COMPLETED = "session_completed"` (`:23`) and the `EventType` Literal union
  includes `"session_completed"` but NOT `"session_ended"` (`:80-113`).
- `syn_collector` enum, by contrast, defines `SESSION_ENDED = "session_ended"`
  (`packages/syn-collector/src/syn_collector/events/types.py:69`). There is NO
  `session_completed` in that enum.
- `AgentEvent.from_dict` imports its type from `syn_shared.events` and maps Claude raw
  `result -> SESSION_COMPLETED` (`models.py:51,67-70`, mapping table at `:60-77`). A
  `/events` payload carrying the collector-valid `session_ended` can pass request-time
  validation at the collector and THEN be unrecognized at persistence, because nothing maps
  `session_ended` to a `syn_shared.events` value.

**Approved minimal vocabulary (all confirmed present in `syn_shared.events`):**
`session_started` (`:22`), `session_completed` (`:23`), `session_error` (`:24`),
`session_summary` (`:25`), `tool_execution_started` (`:17`), `tool_execution_completed`
(`:18`), `tool_execution_failed` (`:55`), `token_usage` (`:33`), `cost_recorded` (`:34`).

**Do not emit `session_ended`.** If the product genuinely wants that name, the correct fix
is to add `SESSION_ENDED` to `syn_shared.events`, to its Literal union, to projections, and
to a compatibility mapping in `_resolve_event_type` BEFORE any adapter emits it. Until then,
session end is `session_completed` (ok/normal) or `session_error` (abnormal).

**Conformance gate:** Increment 0 ships a test that pushes each minimal-set event through
the real `/events` -> `AgentEvent.from_dict` path and asserts the final insert tuple. No
adapter merges until its event_types pass this gate.

### 1.3 The minimal event set EVERY adapter MUST emit (the floor)

The intersection of what L1/L2/L3/L4 prove is extractable on at least the structured-stream
or session-log surface of each harness. Field names use the `syn_shared.events` values from
1.2.

| Capability group | Required event_type | Mandatory `data` fields | Why it is the floor |
|---|---|---|---|
| Session start | `session_started` | `provider`, `model?`, `cwd?`, `source?` | Every harness exposes a session/thread id at start (Claude `system.init`; Codex `thread.started`; Gemini `init`; PI `agent_start`/header). |
| Session end | `session_completed` (or `session_error`) | `reason`, `duration_ms?`, `exit_code?` | Closes the run; drives stale-execution detection. |
| Tool start | `tool_execution_started` | `tool_name`, `tool_use_id`/`call_id`, `input_preview` (redacted), `sequence` | Tool lifecycle is the spine of the trace. |
| Tool end | `tool_execution_completed` (or `tool_execution_failed`) | `tool_name`, `tool_use_id`/`call_id`, `success`, `output_preview` (redacted), `sequence` | Paired with start by id; gives duration + success. |
| Tokens | `token_usage` | normalized token keys (1.4), `model`, `usage_scope`, `source_of_truth` | Tokens are first-class on ALL harnesses; cost is derived. |

**Optional (emit when the surface offers it, never block onboarding on it):** `cost_recorded`
(only Claude OTLP carries native `cost_usd`; Codex/Gemini/PI have NO native dollar cost, so
cost is computed downstream from `token_usage` + a pricing table), `session_summary`,
`user_prompt_submitted`, `git_commit`/`git_push`/..., `subagent_started`/`subagent_stopped`,
`context_compacted`.

### 1.4 Token normalization + TOKEN ACCOUNTING

Two separate problems: (a) field-NAME mapping across harnesses, and (b) accounting scope so
projections do not double-count.

**(a) Field-name mapping.** Match the KEY names the existing projection already writes, so we
do not create a third vocabulary. The orchestration collector writes `cache_creation_tokens`
and `cache_read_tokens`
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ObservabilityCollector.py:132-133`,
and again at `:270-271`). New adapters MUST use those exact key names.

| Canonical `data` key (stored) | Claude | Codex (`turn.completed.usage`) | Gemini (`gen_ai.usage`) | PI (`Usage`) |
|---|---|---|---|---|
| `input_tokens` | `input_tokens` | `input_tokens` | `input` | `input` |
| `output_tokens` | `output_tokens` | `output_tokens` | `output` | `output` (reasoning folded in) |
| `cache_read_tokens` | `cache_read_input_tokens` | `cached_input_tokens` | `cached` | `cacheRead`/`cache_read` |
| `cache_creation_tokens` | `cache_creation_input_tokens` | (none) | (none) | `cacheWrite`/`cache_write` |
| `reasoning_tokens` | (none) | `reasoning_output_tokens` | `thoughts` | (none) |
| `total_tokens` | computed | `total_tokens` | `total` | `totalTokens`/`total_tokens` |
| `model` | `model` | `turn_context.model` | `model` | header `model_id` |

**(b) Accounting scope (the genuinely fiddly part).** Different harnesses report token usage
at different scopes, and naive summing double-counts on resume/compaction. Every
`token_usage` event MUST carry:

- `usage_scope` in `{"turn", "session_total", "cumulative_counter"}`
  - `turn` - usage for one provider response (Codex `turn.completed.usage`; PI per-turn
    `AssistantMessage.usage`; Claude per-assistant-message).
  - `session_total` - an authoritative running total snapshot (Claude `session_summary`;
    Codex rollout `total_token_usage`; PI RPC `get_session_stats`/`get_state`).
  - `cumulative_counter` - a monotonically increasing OTLP-style counter (Gemini
    `gemini_cli.token.usage` metric points).
- `source_of_truth` in `{"stream", "rollout", "otlp", "summary"}` - which surface produced
  this number, so projections can prefer the authoritative one.

**Projection rule:** for `cumulative_counter` and `session_total`, projections DEDUPE or
REPLACE the latest value per `(session_id, model)` rather than summing. Only `turn`-scoped
events are summed. This is the single rule that prevents the resume/compaction double-count
trap that all four harness maps warn about.

### 1.5 The hard constraint: execution_id / phase_id are orchestrator-injected

`execution_id` and `phase_id` are NEVER set by harness-native telemetry; the harness only
carries `session_id` (`models.py:258-260`). They are stamped by the orchestration layer,
which already does this today: `AgentExecutionHandler` passes `todo.execution_id` and
`todo.phase_id` into the stream processor
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/AgentExecutionHandler.py:143-153`),
`ObservabilityCollector` forwards them (`.../ObservabilityCollector.py:106-113`), and
`record_observation` applies them through `insert_one` as TOP-LEVEL fields
(`packages/syn-adapters/src/syn_adapters/events/store_helpers.py:165-170`).

**Rule:** the `ExporterRunner` stamps `execution_id`/`phase_id` as TOP-LEVEL reserved fields
on each canonical event before store insertion. Do NOT bury them only inside `data.context`,
because `from_dict` reads them as top-level keys. An adapter that invents an `execution_id`
from harness data is wrong; it leaves the field absent and lets the runner correlate by
`session_id`.

### 1.6 ORDERING (no sequence column - do not trust time)

`agent_events` has only `time`, no `sequence` column (`schema.py:67-75`). Three of the four
harnesses cannot be ordered by time alone:

- Codex `--json` stdout lines carry NO timestamps (L2); the adapter receipt-stamps them.
- Capture-pane events are receipt-stamped at scrape time, lagging the real event.
- Gemini OTLP metric points and PI stream lines (after the header) carry no per-line time.

**Rule:** every adapter assigns a per-source monotonic `sequence` integer in `data`
(stream line index, rollout byte offset, or pane-frame counter) and carries the harness tool
id (`tool_use_id` for Claude, `call_id` for Codex, `toolCallId` for PI) on BOTH the start and
end event. Tool start/end pairing is by id + sequence, NEVER by time. Projections that need
ordering sort by `(session_id, sequence)`, falling back to `time` only as a coarse tiebreak.

This also feeds dedup: `event_id` SHOULD be source-native where possible (Codex
`thread_id + rollout_path + byte_offset` or `call_id`; PI `session_id + toolCallId + type`;
Claude hook timestamp + hook name + tool id) rather than a content hash, which is unstable
when events are receipt-stamped or replayed from rollout.

### 1.7 REDACTION (a HARD requirement)

Rollout JSONL, session transcripts, `stream-json` output, and tool inputs/outputs carry full
prompts, file contents, secrets, and MCP payloads. The existing store path does NOT protect
against this: `record_observation` strips only `RESERVED_OBSERVATION_KEYS` to prevent envelope
corruption (`store_helpers.py:154`, `safe_data = {k: v for k, v in data.items() if k not in
RESERVED_OBSERVATION_KEYS}`); it does NOT strip or bound payload bodies.

**Rule (mandatory, blocks merge):** each adapter PREVIEWS, BOUNDS, and REDACTS before writing.
Concretely:

- Tool `input`/`args` and `output`/`result` are stored as `input_preview`/`output_preview`,
  truncated to the existing `<=200` char convention, with secret patterns redacted.
- Assistant/user message bodies are NOT stored verbatim; only token counts and a bounded
  preview if any.
- NEVER ship credential stores as a source: Codex `auth.json`/full `config.toml` (MCP bearer
  tokens), Gemini credentials, PI `~/.pi/agent/auth.json`
  (`packages/coding-agent/src/core/auth-storage.ts:59`; Rust `src/auth.rs`).
- Redaction is in the ADAPTER (pure, unit-testable against a fixture containing a planted
  secret), not deferred to the collector, because the collector cannot know which payload
  fields are sensitive per harness.

Operator still owns the policy KNOB (store previews vs strip entirely, section 8), but the
adapter capability to redact is non-optional.

---

## 2. PER-HARNESS EXPORTER ADAPTER PATTERN

### 2.1 The one interface (kept minimal per the review)

```python
# Conceptual. Lives next to the orchestration stream seam (section 4), not in tmux.
# Pure extraction + mapping. No I/O, no route choice, no correlation injection.

class HarnessExporter(Protocol):
    provider: str   # "claude" | "codex" | "gemini" | "pi" | "opencode" | ...

    def capabilities(self) -> CapabilitySet:
        """Probe what THIS install offers, drawn from
        {OTLP, STRUCTURED_STREAM, SESSION_LOG, HOOKS, CAPTURE_PANE}."""

    def session_id(self, raw: RawSignal) -> str:
        """Extract the harness-native session/thread id."""

    def normalize(self, raw: RawSignal) -> list[CanonicalEvent]:
        """Map ONE harness-native signal -> zero or more canonical envelopes.
        event_type from syn_shared.events (1.2); ISO/receipt timestamp;
        session_id; sequence; redacted previews; usage_scope/source_of_truth."""
```

Per the review's over-engineering caution: keep the protocol this small. `capabilities()` is
justified only because Gemini and PI genuinely have multiple implemented surfaces;
`select_surface()`, a full `_EXPORTERS` registry, and the generic OTLP registry are deferred
until a second harness actually lands a row (section 7). `CanonicalEvent` is the envelope of
1.1 plus `sequence`/`usage_scope`/`source_of_truth`/`surface`/`backend`. The adapter is
Lane-2-clean (telemetry only) and unit-testable against a captured fixture file.

### 2.2 Claude adapter (grounded in L1) - the reference

- **Surfaces:** HOOKS (proven, primary), SESSION_LOG (transcript), STRUCTURED_STREAM (`-p`
  JSONL), OTLP (cost only, UNPROVEN to land - see retro).
- **Extraction:** the 14 lifecycle hooks already emit canonical envelopes via `observe.py`
  (`lib/agentic-primitives/plugins/observability/hooks/handlers/observe.py:146-161`);
  transcript tailer reads `~/.claude/projects/**/*.jsonl` for `token_usage`. The work is to
  factor this EXISTING path behind `HarnessExporter`, normalizing any hook name that differs
  from the `syn_shared.events` vocabulary (1.2) before persistence.
- **session_id:** stdin `session_id` else `CLAUDE_SESSION_ID` else `"unknown"`
  (`observe.py:176`).
- **Status:** exists in all but name; it is Increment 0's refactor target.

### 2.3 Codex adapter (grounded in L2) - the next harness to build

- **Surfaces:** STRUCTURED_STREAM (`codex exec --json`, cleanest live path), SESSION_LOG
  (rollout JSONL + `state_5.sqlite` index), HOOKS (exist, payload unverified). NO confirmed
  OTLP for CLI runs.
- **Phase-1 scope (per review reduction):** from `--json` emit ONLY `session_started`
  (`thread.started`) and `token_usage` (`turn.completed.usage`, `usage_scope="turn"`). Do
  NOT claim full live tool start/end from the stream until a fixture proves `function_call`
  and `function_call_output` appear on the selected surface. The L2 evidence shows tool
  detail is stronger in rollout `response_item` records than in real-time stdout.
- **Phase-2 add:** rollout-based tool pairing by `call_id`, plus the post-run
  `state_5.sqlite:threads` join for authoritative timestamps and git metadata. Cursor by
  `(thread_id, rollout_path, byte_offset)`.
- **Stream has no timestamps:** receipt-stamp + assign `sequence` (1.6).
- **Cost:** none native; price externally from normalized tokens.
- **Redaction (1.7):** treat rollout as opaque; never scrape `auth.json`/full `config.toml`/
  `logs_2.sqlite` as primary.

### 2.4 Gemini adapter (grounded in L3)

- **Surfaces:** STRUCTURED_STREAM (`--output-format stream-json`, the recommended START
  path), OTLP-native (real in the CLI, but does NOT land through the current collector - see
  3.2), SESSION_LOG (`~/.gemini/tmp/<proj>/chats/*.jsonl`, version-fragile `$set` journal),
  HOOKS.
- **Extraction (orchestrated):** `gemini --output-format stream-json --session-id <our-uuid>`;
  `init -> session_started`, `tool_use`/`tool_result -> tool lifecycle`,
  `result -> token_usage (usage_scope="turn") + session_completed`. Injecting `--session-id`
  pre-correlates to our aggregate id.
- **OTLP path:** deferred to the gated top layer (section 3); requires protocol work, not
  available today.
- **Cost:** none native; price from token type breakdown.
- **MIGRATION RISK - Antigravity (`agy`):** Gemini CLI deprecates ~2026-06-18 for free/Pro/
  Ultra tiers; JSONL path + schema change, OTLP unconfirmed, hooks survive. `capabilities()`
  must probe, not assume. Spike owed (section 8).

### 2.5 opencode adapter (kept)

opencode remains the worked reference for a plugin-hook harness not yet wired
(`docs/features/opencode-plugin-observability.md`, issue #51). It is onboarded by writing a
`HarnessExporter` against that design: capabilities `{HOOKS, SESSION_LOG}`, plugin events ->
canonical envelope, `--oc` ntm flag already reserved.

### 2.6 PI adapter (grounded in L4 - now concrete, de-blocked)

PI is identified: **the "Pi" agent harness by earendil-works (Mario Zechner)**, npm
`@earendil-works/pi-coding-agent`, with a Rust port (`Dicklesworthstone/pi_agent_rust`). Both
binaries are named `pi` and CONVERGE on one observability surface, so ONE adapter + two
fixtures covers both.

- **`capabilities()` ->** `{STRUCTURED_STREAM, HOOKS, SESSION_LOG}`; `OTLP=false` (design-only
  in TS, JS stub in Rust). The probe records whether HOOKS is in-process TS modules
  (canonical) or WASM/WIT (Rust); `normalize()` does not care.
- **Primary source (STRUCTURED_STREAM):** `pi -p --mode json "<prompt>"` writes a
  `SessionHeader` line then one `AgentEvent` JSONL per line on stdout
  (`packages/coding-agent/src/modes/print-mode.ts:184-196`; Rust `src/main.rs:6535,6809`).
  Event `type` values: `agent_start`, `agent_end`, `turn_start`/`turn_end`,
  `message_start`/`update`/`end`, `tool_execution_start`/`update`/`end`.
- **session_id:** `SessionHeader.id`. PI can PIN it at spawn (`--session-id` / `--session-dir`),
  putting PI in the easy-correlation tier with Gemini, not the after-the-fact-join tier of
  Codex. Per 1.5 the adapter still only sets `session_id`; the runner injects execution/phase.
- **Event mapping (collector-floor, using 1.2 vocabulary):**
  - `agent_start` / header -> `session_started` (`data`: provider, model = header `model_id`,
    cwd). Receipt-stamp; assign sequence.
  - `agent_end` -> `session_completed` (or `session_error` if `error?` present);
    `data.exit_code` from the wrapped process for one-shot `-p`.
  - `tool_execution_start` -> `tool_execution_started` (`tool_name=toolName`,
    `tool_use_id=toolCallId`, `input_preview` = REDACTED `args`).
  - `tool_execution_end` -> `tool_execution_completed`/`tool_execution_failed`
    (`success=!isError`, `output_preview` = REDACTED `result`). Pair by `toolCallId`.
  - per-turn `AssistantMessage.usage` off `turn_end.message`/`message_end.message` ->
    `token_usage`, `usage_scope="turn"`, `source_of_truth="stream"`. Token mapping per 1.4
    (`input/output/cacheRead/cacheWrite/totalTokens`; no separate reasoning field).
- **Hybrid billing:** PI is multi-provider; billing is configurable, defaulting to
  API/per-token unless an OAuth/subscription login (Claude Max, Codex, Copilot) is used. Token
  counts are always accurate; the PI-computed `cost` is a list-price estimate only, so emit
  `cost_recorded` only if the owned pricing table is trusted (section 8).
- **ntm flag:** reserve **`--pi`** (next free slot after `--cc/--cod/--gmi/--oc`). Spawn:
  `ntm spawn <org>--<repo> --pi=N[:model[:effort]]`. The launcher wraps `pi -p --mode json`
  and pipes stdout to the exporter for observed runs.
- **Runtime recommendation:** target `pi_agent_rust` as the install on this VPS (single
  curl-installed binary, matches the operator's existing Dicklesworthstone tooling), treat
  the canonical earendil-works repo as the schema source of truth, and pin both with a
  captured `--mode json` fixture per binary version.
- **Redaction (1.7):** `args`/`result`/message bodies in stream AND transcript carry full
  prompts; preview-truncate and never ship `~/.pi/agent/auth.json`.

### 2.7 Surface preference order (default, overridable per `capabilities()`)

Because OTLP is unproven to land (retro), the default order leads with the proven channels:
**(1) structured stream** (Codex `--json`, Gemini `stream-json`, PI `--mode json`, Claude
`-p`) for orchestrated runs -> **(2) hooks** (Claude proven primary; Codex/Gemini/PI/opencode
available) for in-process lifecycle -> **(3) session-log / rollout tail** for interactive +
backfill -> **(4) capture-pane scrape** as last resort -> **(5) OTLP** ONLY once the retro
gates are green and a generic receiver exists (section 3). Claude is the exception where hooks
ARE the proven primary. v1 placed OTLP first; this is the explicit downgrade.

---

## 3. OTLP TOP LAYER (downgraded to a LATER, GATED layer)

### 3.1 What v1 got wrong, what is actually true today

v1 presented OTLP as an already-existing tidy top surface and put it first in the preference
order. The review and the retro both refute that:

- The collector has OTLP-JSON routes over FastAPI, NOT a general OTLP receiver. The routes
  call `request.json()` and parse JSON
  (`packages/syn-collector/src/syn_collector/collector/routes.py:53-91`). There is NO gRPC
  receiver on `:4317` in the checked code.
- The metric/log name mapping is hardcoded to Claude:
  `_METRIC_TO_EVENT_TYPE`/`_LOG_EVENT_TO_EVENT_TYPE` key off `claude_code.*`
  (`packages/syn-collector/src/syn_collector/collector/otlp.py:39-67`). Gemini's
  `gemini_cli.*`/`gen_ai.*` will not land as-is, and Gemini OTLP defaults to gRPC.
- The 2026-06-18 experiment (`experiments/2026-06-18--observability--interactive-tmux-otel-parity/verdict.md`):
  C0 baseline produced 0 OTLP rows even for `claude -p`; C1/C2 interactive turns never
  completed; C3 confirmed network reachability (HTTP 200 to `/v1/metrics`). So the OTLP
  failure is wiring/extraction, not connectivity, and native OTLP parity remains UNPROVEN.

### 3.2 The boundary, restated

```
   TOP (LATER, GATED)   OTLP integration surface
                        - needs (a) a protocol decision (force HTTP-JSON per harness, or
                          stand up a real gRPC 4317 receiver) and (b) a provider-name
                          registry (claude_code., gemini_cli., gen_ai.) replacing the
                          Claude-only dict. Ships only after the retro gates are green.
   ==== BOUNDARY: above = standard OTLP; below = harness goo, /events is load-bearing ====
   BOTTOM (NOW)         Per-harness ExporterAdapters -> POST /events (CollectedEvent)
                        Claude hooks | Codex --json + rollout | Gemini stream-json |
                        PI --mode json | opencode plugin | capture-pane (last resort)
```

`/events` + `CollectedEvent` is the load-bearing route the build targets now. OTLP is a
presentation/integration layer added later, gated on the retro and on the two prerequisites
above. Until then, no harness's "full observability" claim may depend on OTLP; the floor is
the hook/stream minimal set of 1.3.

---

## 4. THE MINIMAL SEAM (orchestration stream, NOT interactive-tmux)

### 4.1 Where the first runner plugs in (corrected)

v1 proposed hosting the exporter registry inside the interactive-tmux pane driver. The review
corrects this: the `_ADAPTERS` registry IS real
(`lib/agentic-primitives/providers/workspaces/interactive-tmux/driver/interactive_tmux.py:543`,
with `_AdapterContext` at `:196`), and it proves a registry pattern for TUI control quirks,
but it is NOT the natural home for observability. The PROVEN observability path for
orchestrated runs is the execution stream + `ObservabilityCollector`, which already stamps
session/execution/phase/workspace/model
(`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ObservabilityCollector.py:66-80,106-113`).

**Rule:** the first `HarnessExporter` runner plugs in beside `EventStreamProcessor` /
`AgentExecutionHandler`, where raw structured stdout already exists and correlation IDs are
already threaded. The interactive-tmux capture-pane exporter is added LATER (section 5),
consuming `capture_response()` + session logs. This keeps the clean path decoupled from the
brittle interactive path.

### 4.2 What new code is needed (kept minimal)

1. **`HarnessExporter` protocol + `CanonicalEvent`** (envelope of 1.1 plus `sequence`,
   `usage_scope`, `source_of_truth`, `surface`, `backend`). Pure data + mapping.
2. **An `ExporterRunner`** that owns the two things the adapter must NOT: route selection
   (`/events` batch today; OTLP later) and TOP-LEVEL `execution_id`/`phase_id` stamping (1.5).
   Reuse the existing collector client
   (`packages/syn-adapters/src/syn_adapters/collector/client*.py`) for retry/batching.
3. **Fixture conformance tests** per harness/version (the planted-secret redaction test of
   1.7 and the vocabulary-landing test of 1.2 live here).

Deferred until a second harness lands a row: a full `_EXPORTERS` registry, `select_surface()`,
`capabilities()`-driven dispatch, and the generic OTLP name registry. Nothing in
`agent_events`, `AgentEvent.from_dict`, or the collector routes changes; the seam is additive.

---

## 5. INTERACTIVE vs structured stream (one adapter shape, late for capture-pane)

### 5.1 Two extraction modes

| | structured stream (`-p` / `exec --json` / `stream-json` / `--mode json`) | interactive-tmux (capture-pane) |
|---|---|---|
| Surface | structured JSONL on stdout | rendered TUI; only `tmux capture-pane -p` text |
| Event source | parse each JSONL line | scrape pane buffer + readiness heuristics (`interactive_tmux.py:327-345`) |
| Token/cost | carried in `result`/`turn.completed.usage`/`turn_end.message.usage` | NOT in the pane; must come from the on-disk session log/rollout/transcript |
| Lifecycle | explicit `init`/`thread.started`/`agent_start`/`result` | inferred from pane-state transitions (`:819-851`) |
| Timestamps + ordering | per-line (Claude) or receipt-stamped + `sequence` (Codex/PI) | receipt-stamped + frame `sequence` |

### 5.2 The interactive composite (a LATE parity path, not the floor)

In interactive mode the pane scrape gives lifecycle/turn boundaries but NOT tokens/tools-with-
args, which only exist in the on-disk session log the harness writes anyway. So the
interactive adapter is a COMPOSITE: **capture-pane for lifecycle + session-log tail for
tokens/tools**, correlated by `session_id`. Per the review, this depends on brittle TUI
readiness heuristics and multiple internal log schemas; it is the WEAKEST path and ships late,
not in the initial floor.

### 5.3 Why one adapter shape still serves both

`normalize(raw)` is agnostic to where `raw` came from: a JSONL stream line, a rollout SQLite
row, a PI `ExtensionEvent`, or a captured pane frame are all just `RawSignal` to map. Both
modes feed the SAME `normalize()` and produce the SAME `CanonicalEvent`; only `capabilities()`
and the runner's polling loop differ. So the design does not fork into separate batch vs
interactive subsystems; it is one registry with per-surface capability flags.

---

## 6. CROSS-LINK: the 2026-06-18 retro + open risks

### 6.1 What the retro established (verdict: inconclusive)

`experiments/2026-06-18--observability--interactive-tmux-otel-parity/verdict.md`: C0 baseline
FAILED (0 OTLP rows even for `claude -p`); C1/C2 interactive turns never completed (confounded,
not proven absent); C3 PASS (network reachable, HTTP 200 to `/v1/metrics`). Conclusion: the
proven channel is HOOK + SESSION-LOG + EXPORTER into `/events`; OTLP is unproven to land. This
is WHY OTLP is downgraded (section 3), Increment 0 is the proven `/events` path (section 7),
and `capabilities()` probes rather than assumes.

### 6.2 Open risks

1. **OTLP landing is unproven end-to-end.** Do not gate any harness's full-observability claim
   on OTLP until a green rerun exists. Floor is the stream/hook minimal set (1.3).
2. **Two retro release gates remain open:** the baseline OTLP pipeline must be unblocked AND
   interactive workspace trust automation fixed before the OTLP-parity rerun is meaningful.
   These block the top layer, not the adapter floor.
3. **Gemini -> Antigravity migration:** recommended Gemini surface may not survive `agy`.
   `capabilities()` mitigates; the spike is owed.
4. **Codex has no native OTLP and no verified hook payload:** leans on `--json` + rollout/
   SQLite, internal-schema-fragile, may leak prompts. Treat rollout as opaque; redact (1.7).
5. **Session-log schemas are version-fragile across all harnesses** (Gemini `$set` journal,
   Codex rollout, Claude transcript shape, PI serde/TS field renames). Tie each adapter to a
   captured-fixture conformance test per harness version.
6. **Cost is computed, not observed, for Codex/Gemini/PI.** A stale pricing table silently
   corrupts cost. The pricing table is an operational dependency (section 8).
7. **Capture-pane scraping is inherently brittle** (readiness heuristics already needed
   three-signal hardening, `interactive_tmux.py:327-345`). Strictly last-resort; always pair
   with the on-disk session log for authoritative tokens/tools.
8. **Vocabulary divergence (NEW, highest-risk):** `syn_collector` enum and `syn_shared.events`
   disagree (`session_ended` vs `session_completed`). Persistence validates against
   `syn_shared.events`. Fix the contract (1.2) before building adapters.
9. **No ordering column + receipt-stamped events (NEW):** time ordering is unsafe; rely on
   per-source `sequence` + tool id pairing (1.6).
10. **Redaction is not free in the store path (NEW):** `record_observation` strips only
    reserved keys, not secrets (`store_helpers.py:154`). Adapters must redact (1.7).

---

## 7. PHASED BUILD PLAN (smallest shippable first)

| Phase | Deliverable | Surface(s) | Risk | Proves |
|---|---|---|---|---|
| **0** | (a) Fix the vocabulary contract: define `CanonicalAgentEvent` targeting `syn_shared.events` values (1.2). (b) Fixture test that sends `session_started`, `session_completed`, `tool_execution_started`, `tool_execution_completed`, `token_usage` through real `/events` -> `AgentEvent.from_dict` and asserts the insert tuple. (c) Factor the EXISTING Claude hook path behind `HarnessExporter` with a no-op `ExporterRunner` on the current `/events` route. (d) Redaction unit test with a planted secret. | Claude hooks + store path | very low | the REAL store vocabulary lands, and the interface against the one proven-landing harness. No behavior change. |
| **1** | `ExporterRunner` (route selection + TOP-LEVEL execution_id/phase_id stamping, 1.5) wired beside `EventStreamProcessor`/`AgentExecutionHandler` (NOT tmux, section 4). | Claude stream | low | the clean-path seam; orchestrator correlation lands. |
| **2** | Codex adapter, reduced: `exec --json` -> `session_started` + `token_usage` (turn scope) ONLY, with `sequence` + receipt-stamp. | Codex structured stream | medium | second harness on the floor; token accounting (1.4); the richest structured non-Claude surface. |
| **3** | Codex rollout tool pairing by `call_id` + `state_5.sqlite` join. | Codex rollout/SQLite | medium | full tool lifecycle once a fixture proves `function_call`/`function_call_output`. |
| **4** | PI adapter: `pi -p --mode json` -> full floor (section 2.6), one adapter + TS/Rust fixtures, `--pi` flag reserved. | PI structured stream | medium | third harness; `--session-id` pre-correlation; no post-run join needed. |
| **5** | Gemini adapter via `--output-format stream-json` (orchestrated path). | Gemini stream-json | medium | fourth harness; `--session-id` pre-correlation. |
| **6** | Generic OTLP name registry + protocol decision + Gemini/Claude OTLP receiver path. GATED on retro gate #2. | OTLP top layer | high | the tidy top surface, after a green OTLP rerun. |
| **7** | Interactive composite: capture-pane lifecycle + session-log tail (5.2); Codex Mode B + Gemini JSONL + PI session-log backfill. | capture-pane + session-log | high | interactive parity; the weakest path, last. |
| **8** | Antigravity `agy` capability probe + adapter swap; opencode plugin adapter. | per `capabilities()` | high / blocked | future-harness generality. |

Each phase is independently shippable and adds at most one harness or one surface. The floor
is reached for a harness at the END of its phase; OTLP enrichment is always a later,
separately-gated add. Codex is deliberately the FIRST non-Claude harness (Phase 2) because its
`--json` stream is the richest structured surface; PI follows (Phase 4) as the cleanest pin-
your-own-session-id harness with no post-run join.

---

## 8. OPERATOR DECISIONS STILL NEEDED

1. **Vocabulary contract direction (BLOCKING, highest priority, 1.2).** Confirm adapters emit
   `syn_shared.events` values (`session_completed`, not `session_ended`). If the product wants
   the name `session_ended`, authorize adding it to `syn_shared.events` + Literal union +
   projections + `_resolve_event_type` mapping FIRST. No adapters merge until this is decided.
2. **Redaction policy (BLOCKING for any adapter, 1.7).** Adapter-level redaction is mandatory;
   the operator chooses the KNOB: store bounded previews (`<=200` char) vs strip payload bodies
   entirely, per harness. Confirm whether prompt bodies may be stored at all.
3. **Token-key + accounting standard (1.4).** Confirm new adapters use the existing stored key
   names (`cache_creation_tokens`/`cache_read_tokens`) and the `usage_scope`/`source_of_truth`
   fields, with projections dedup/replace (not sum) for cumulative scopes. Approve the
   projection change.
4. **OTLP timing + protocol (downgraded, section 3).** Confirm OTLP ships AFTER the two retro
   gates are green (recommendation: floor first, OTLP later). Decide protocol: force HTTP-JSON
   per harness, or stand up a gRPC 4317 receiver for Gemini's default.
5. **Retro release gates (BLOCKING for the OTLP top layer).** Prioritize unblocking the
   baseline OTLP pipeline and interactive workspace trust automation, then schedule the
   OTLP-parity rerun.
6. **Pricing table ownership (operational).** Codex/Gemini/PI have no native dollar cost; who
   owns and refreshes the per-model pricing table, and where does it live?
7. **PI install + flag (section 2.6).** Approve targeting `pi_agent_rust` (curl binary) as the
   VPS runtime with the canonical earendil-works repo as schema source of truth, and reserve
   the `--pi` ntm flag. Confirm the hybrid billing model in the model card (configurable;
   API-billed unless an OAuth/subscription login is used).
8. **Antigravity (`agy`) spike (BLOCKING for Gemini longevity).** Authorize the 1-hour spike to
   confirm (a) whether `agy` emits OTLP, (b) the new JSONL path/schema, (c) the headless flag
   name. Decide: build against Gemini CLI now and accept a re-map, or wait for `agy`.
9. **Surface preference override per harness (2.7).** Confirm the default order (structured
   stream -> hooks -> session-log -> capture-pane -> OTLP-when-green), noting Claude's hook
   exception. Operator may pin a different primary per harness for cost/reliability.

---

## Appendix - citation index (spot-checked 2026-06-21)

- Landing schema: `packages/syn-adapters/src/syn_adapters/events/schema.py:67-75`.
- Normalizer: `packages/syn-adapters/src/syn_adapters/events/models.py:226-262` (flatten +
  optional IDs `:258-260`), `:51,60-77` (`_resolve_event_type` mapping, `result ->
  SESSION_COMPLETED`).
- Persisted vocabulary (SOURCE OF TRUTH): `packages/syn-shared/src/syn_shared/events/__init__.py:22-25`
  (`session_started`/`session_completed`/`session_error`/`session_summary`), `:80-113` (Literal
  union, no `session_ended`).
- Divergent collector enum: `packages/syn-collector/src/syn_collector/events/types.py:68-69`
  (`session_started`/`session_ended`).
- Token keys already stored: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ObservabilityCollector.py:132-133,270-271`
  (`cache_creation_tokens`/`cache_read_tokens`), correlation forward `:106-113`.
- Correlation stamping path: `.../handlers/AgentExecutionHandler.py:143-153`,
  `packages/syn-adapters/src/syn_adapters/events/store_helpers.py:154` (strips reserved keys
  only, NOT secrets), `:165-170` (top-level execution/phase to `insert_one`).
- Collector routes / OTLP: `packages/syn-collector/src/syn_collector/collector/routes.py:53-91`
  (JSON routes, no gRPC), `.../collector/otlp.py:39-67` (Claude-only metric/log name map).
- Per-agent adapter registry to mirror (control quirks, NOT obs home):
  `lib/agentic-primitives/providers/workspaces/interactive-tmux/driver/interactive_tmux.py:196`
  (`_AdapterContext`), `:543` (`_ADAPTERS`), `:327-345` (readiness), `:819-851` (lifecycle).
- Claude hooks: `lib/agentic-primitives/plugins/observability/hooks/handlers/observe.py:146-161,176`.
- Retro: `experiments/2026-06-18--observability--interactive-tmux-otel-parity/verdict.md`.
- PI surface: `obs-L4-pi-surface.md` (canonical `/tmp/pi_canon_v2`; Rust `/tmp/pi_rust_v2`);
  stream `packages/coding-agent/src/modes/print-mode.ts:184-196`, Rust `src/main.rs:6535,6809`;
  usage `packages/ai/src/types.ts:283-298`, Rust `src/model.rs:218`; auth
  `packages/coding-agent/src/core/auth-storage.ts:59`, Rust `src/auth.rs`.
- opencode worked example: `docs/features/opencode-plugin-observability.md` (issue #51).
- Phase-1 inputs: `~/swarm-tasks/obs-L1..L4-*.md`, `obs-L5-design.md` (v1, superseded),
  `obs-L5-review.md`.
</content>
</invoke>
