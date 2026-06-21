# Obs L5 - Standardized Cross-Harness Observability Design

**Scope:** Synthesize the four Phase-1 surface maps (L1 Claude ground truth, L2 Codex,
L3 Gemini, L4 PI/general) into ONE harness-agnostic observability design for syntropic137.
Design only; no repo source modified.

**Repo:** `/data/projects/synstress` (syntropic137 + vendored `lib/agentic-primitives`).
Citations are `file:line` relative to that root.

**Inputs:** `obs-L1-claude-groundtruth.md`, `obs-L2-codex-surface.md`,
`obs-L3-gemini-surface.md`, `obs-L4-pi-surface.md`, `cross-harness-observability.brief.md`.

**Design north star (from the brief):** generalize the mechanism that ALREADY works for
Claude today (hook + session-log + exporter into `agent_events`), present a clean
OTLP-shaped surface ON TOP, and keep the messy per-harness extraction underneath. OTLP is
a presentation layer, not the load-bearing channel (see the 2026-06-18 retro, section 6).

---

## 0. One-paragraph thesis

Every harness already lands in the same place: the `agent_events` hypertable
(`time, event_type, session_id, execution_id, phase_id, data`), normalized by one function,
`AgentEvent.from_dict` (`packages/syn-adapters/src/syn_adapters/events/models.py:226-262`).
The generalization is therefore NOT a new pipeline; it is a thin **ExporterAdapter** contract
per harness that turns harness-native telemetry (hooks / session-log JSONL / rollout SQLite /
stdout stream / capture-pane scrape) into the canonical envelope, mints a deterministic
`event_id`, and delivers it through one of the two routes that already exist. The orchestrator
(not the harness) injects `execution_id`/`phase_id`, because harness-native telemetry only
ever carries `session_id` (L1 section 2d, `models.py:258-260`). On top of the per-harness
extraction we expose an OTLP/collector receiver as the tidy integration seam; underneath, each
adapter does whatever ugly thing its harness requires.

---

## 1. NORMALIZED EVENT SCHEMA

### 1.1 The landing contract (unchanged - this is the target, not a proposal)

All harnesses must produce rows that fit the existing 6-column shape
(L1 section 2c, `packages/syn-adapters/src/syn_adapters/events/schema.py:67-86`):

```sql
agent_events(
  time         TIMESTAMPTZ NOT NULL,   -- event time (adapter stamps if harness omits)
  event_type   TEXT        NOT NULL,   -- a syn_collector EventType enum VALUE
  session_id   TEXT        NOT NULL,   -- the ONLY correlation key the harness carries
  execution_id TEXT,                   -- orchestrator-injected, else NULL
  phase_id     TEXT,                   -- orchestrator-injected, else NULL
  data         JSONB       NOT NULL    -- everything else (provider, model, tokens, args...)
)
```

The on-the-wire envelope each adapter emits is the shared emitter shape
(L1 section 1c, `lib/agentic-primitives/lib/python/agentic_events/.../emitter.py:51-79`):

```json
{
  "event_type": "<EventType value>",
  "timestamp":  "<ISO-8601 UTC>",
  "session_id": "<id or 'unknown'>",
  "provider":   "<claude|codex|gemini|...>",
  "context":    { "...operation-specific..." },
  "metadata":   { "...optional..." }
}
```

`AgentEvent.from_dict` keys off `event_type` + `session_id` + `timestamp` and folds the rest
into `data` (L1 section 2d). Any adapter that produces this object lands cleanly through both
routes. No schema change is required to onboard a new harness; that is the whole point.

### 1.2 Target the COLLECTOR enum, not the emitter strings

L1 section 6 documents real vocab skew: the emitter says `session_completed` while the
collector enum canonical value is `session_ended`
(`packages/syn-collector/src/syn_collector/events/types.py:68-69`). Projections query the
collector values (e.g. `tool_execution_completed` at `queries.py:340`). **Rule for every
adapter: emit the `syn_collector.events.types.EventType` VALUE, not a harness-native or
legacy-alias string.** Confirmed values an adapter may use:
`session_started`(:68), `session_ended`(:69), `tool_execution_started`(:75),
`tool_execution_completed`(:76), `token_usage`(:84), `cost_recorded`(:114).

### 1.3 The minimal event set EVERY adapter MUST emit (the common denominator)

This is the floor for "full observability" parity. It is the intersection of what L1/L2/L3
proved is extractable on at least the structured-stream or session-log surface of each harness.

| Capability group | Required EventType | Mandatory `data` fields | Why it is the floor |
|---|---|---|---|
| Session start | `session_started` | `provider`, `model?`, `cwd?`, `source?` | Every harness exposes a session/thread id at start (L1 1a; L2 `thread.started`; L3 `init`). |
| Session end | `session_ended` | `reason`, `duration_ms?`, `exit_code?` | Closes the run; drives stale-execution detection. |
| Tool start | `tool_execution_started` | `tool_name`, `tool_use_id`/`call_id`, `input_preview` | Tool lifecycle is the spine of the trace (L1 PreToolUse; L2 `function_call`; L3 `tool_use`). |
| Tool end | `tool_execution_completed` | `tool_name`, `tool_use_id`/`call_id`, `success`, `output_preview` | Paired with start by id; gives duration + success. |
| Tokens | `token_usage` | `input_tokens`, `output_tokens`, `cache_read?`, `cache_creation?`, `reasoning?`, `model` | Tokens are first-class on ALL three harnesses; cost is derived. |

**Optional / nice-to-have (emit when the surface offers it, never block onboarding on it):**
`cost_recorded` (only Claude OTLP carries native `cost_usd`, L1 section 3; Codex/Gemini have
NO native dollar cost - L2/L3 - so cost is computed downstream from `token_usage` + a pricing
table), `user_prompt_submitted`, `git_commit`/`git_push`/... , `subagent_started`/`stopped`,
`pre_compact`, `notification_sent`.

### 1.4 Token normalization (the one genuinely fiddly field)

Each harness names token dimensions differently. Adapters MUST normalize into a single
`token_usage.data` vocabulary so projections do not branch per provider:

| Canonical `data` key | Claude (transcript/OTLP) | Codex (`turn.completed.usage` / `token_count`) | Gemini (`tokens` / `gen_ai.usage`) |
|---|---|---|---|
| `input_tokens` | `input_tokens` | `input_tokens` | `input` / `gen_ai.usage.input_tokens` |
| `output_tokens` | `output_tokens` | `output_tokens` | `output` / `gen_ai.usage.output_tokens` |
| `cache_read` | `cache_read_input_tokens` | `cached_input_tokens` | `cached` |
| `cache_creation` | `cache_creation_input_tokens` | (none) | (none) |
| `reasoning` | (none) | `reasoning_output_tokens` | `thoughts` |
| `total` | computed | `total_tokens` | `total` |
| `model` | `model` | `threads.model` / `turn_context.model` | `model` |

Carry a `per_turn` vs `cumulative` flag in `data`: L2 warns the live stream
`turn.completed.usage` is per-turn while rollout `total_token_usage` is cumulative; double-
counting on resume/compaction is the trap.

### 1.5 The hard constraint, restated and made a rule

`execution_id` and `phase_id` are NEVER set by harness-native telemetry (L1 section 2d,
`models.py:258-260`; Claude hooks only know `session_id`, `observe.py:176`). They are
injected by the orchestrator/workspace via the `context:{}` mechanism (section 4.3). An
adapter that invents an `execution_id` from harness data is wrong; it must leave the field
absent and let the orchestration layer correlate by `session_id`.

---

## 2. PER-HARNESS EXPORTER ADAPTER PATTERN

### 2.1 The one interface (the only new abstraction)

```python
# Conceptual. Lives in agentic_events (see section 4). stdlib-typed, no business logic.

class HarnessExporter(Protocol):
    provider: str                       # "claude" | "codex" | "gemini" | ...

    def capabilities(self) -> CapabilitySet:
        """Probe what THIS install offers: {OTLP, STRUCTURED_STREAM,
        SESSION_LOG, HOOKS, CAPTURE_PANE}. Drives surface selection."""

    def session_id(self, raw: RawSignal) -> str:
        """Extract the harness-native session/thread id."""

    def normalize(self, raw: RawSignal) -> list[CanonicalEvent]:
        """Map ONE harness-native signal -> zero or more canonical envelopes
        (event_type from the collector enum, ISO timestamp, session_id, data)."""

    def event_id(self, ev: CanonicalEvent) -> str:
        """Deterministic hash(session_id+type+timestamp+content) for dedup."""
```

`CanonicalEvent` is exactly the envelope of section 1.1. The adapter does NOT choose the
route or inject `execution_id`/`phase_id`; the surrounding runner does (section 4). The adapter
is pure extraction+mapping, which keeps it Lane-2-clean (telemetry only, L4 point 5) and unit-
testable against a captured fixture file.

A `CapabilitySet` returned by `capabilities()` is what lets a single registry serve harnesses
with wildly different surfaces. This is L3's CapabilityProbe and L4's "source of these signals"
checklist, promoted to the interface.

### 2.2 Claude adapter (grounded in L1)

- **Surfaces available:** HOOKS (proven, primary), SESSION_LOG (transcript), OTLP (cost only),
  STRUCTURED_STREAM (`-p` JSONL).
- **Extraction:** the 14 lifecycle hooks already emit canonical envelopes via `observe.py`
  (L1 1a, `hooks/handlers/observe.py:146-161`); the adapter is essentially already built and
  is the reference implementation. Transcript tailer reads `~/.claude/projects/**/*.jsonl`
  for `token_usage` (L1 section 4, `watcher/transcript_parser.py:21-72`). OTLP adds per-call
  `cost_usd` + token breakdown via `claude_code.*` metric names (L1 section 3, `otlp.py:54-67`).
- **session_id:** stdin `session_id` else `CLAUDE_SESSION_ID` else `"unknown"` (`observe.py:176`).
- **What stays Claude-specific (L1 section 6):** hook names, `claude_code.*` OTLP metric names,
  transcript path/shape, `_resolve_event_type` raw aliases (`models.py:233-242`).
- **Status:** this adapter exists in all but name; the work is to factor it behind the
  `HarnessExporter` interface so the others can mirror it.

### 2.3 Codex adapter (grounded in L2)

- **Surfaces available:** STRUCTURED_STREAM (`codex exec --json`, cleanest live path),
  SESSION_LOG (rollout JSONL + `state_5.sqlite` index), HOOKS (exist, payload unverified).
  NO confirmed OTLP for CLI runs (L2 section 8).
- **Extraction, Mode A (syntropic launches the run):** wrap `codex exec --json`; map
  `thread.started -> session_started`, `turn.started`/`turn.completed -> turn lifecycle,
  `turn.completed.usage -> token_usage`, `item.completed` tool items -> tool lifecycle
  (L2 section 1, "Extraction Recipes"). Stream has NO timestamps, so the adapter stamps receipt
  time. After exit, join `thread_id` to `state_5.sqlite:threads` for authoritative timestamps,
  tool calls, git metadata (L2 sections 2-3).
- **Extraction, Mode B (interactive / unwrapped):** tail `state_5.sqlite:threads`
  (`updated_at_ms > watermark`) + the rollout JSONL by `rollout_path`, cursor by
  `(thread_id, rollout_path, byte_offset)` (L2 "Mode B").
- **Tool pairing:** `function_call` + `function_call_output` paired by `call_id` (L2 section 2).
- **Cost:** none native; price externally from the normalized token dims (L2 "Tokens and cost").
- **Caveats to honor:** never scrape `auth.json` / full `config.toml` (MCP bearer tokens) /
  `logs_2.sqlite` as primary (L2 "Do not scrape").

### 2.4 Gemini adapter (grounded in L3)

- **Surfaces available:** OTLP-NATIVE (real, confirmed - `gemini_cli.token.usage`,
  `OTEL_EXPORTER_OTLP_ENDPOINT`, L3 section 3/6), STRUCTURED_STREAM
  (`--output-format stream-json`, L3 section 4), SESSION_LOG (`~/.gemini/tmp/<proj>/chats/*.jsonl`,
  a `$set` snapshot journal - version-fragile, L3 section 2), HOOKS (`BeforeTool` etc, L3 1.3).
- **Extraction (orchestrated):** `gemini --output-format stream-json --session-id <our-uuid>`;
  `init -> session_started`, `tool_use`/`tool_result -> tool lifecycle`,
  `result -> token_usage + session_ended` (L3 section 4/9). Injecting `--session-id` pre-
  correlates to our aggregate id - a capability Claude/Codex do not cleanly offer.
- **Extraction (interactive user):** enable telemetry to OUR collector OTLP route
  (`telemetry.enabled=true`, `otlpEndpoint=<syn-collector>`, L3 3.1); ingest
  `gemini_cli.tool_call`, `gemini_cli.token.usage`, `gen_ai.*` keyed by `session.id`.
- **Cost:** none native; price from token `type` breakdown (input/output/cache/thought/tool).
- **MIGRATION RISK - Antigravity (`agy`), L3 section 7:** Gemini CLI deprecates ~2026-06-18 for
  free/Pro/Ultra tiers. JSONL path + schema CHANGE (`brain/<id>/.system_generated/logs/
  transcript*.jsonl`, per-line `step_index/source/type`); OTLP support UNCONFIRMED; hooks
  survive. This is exactly why `capabilities()` is in the interface: the adapter must probe,
  not assume. Run the 1-hour `agy` OTLP spike before committing (operator decision, section 8).

### 2.5 The GENERAL adapter pattern (PI and any future harness, grounded in L4)

PI is unidentifiable from this box (L4 TL;DR): a single placeholder line in the model card,
no binary, no flag. So PI gets no concrete adapter yet - it gets the **5-point onboarding
checklist** that the `HarnessExporter` interface operationalizes (L4 "general pattern"):

1. **Find a telemetry source** - at least one of {structured stream, plugin/hook API, native
   OTLP}. If none exist, the harness cannot be observed without upstream changes - that is the
   first gate (L4). `capabilities()` encodes the answer.
2. **Pin a session identity** - stable `session_id` per run + provider/model tags.
3. **Map native -> canonical events** - the minimal set of section 1.3.
4. **Pick a transport/sink** - batched retrying HTTP `POST /events` or OTLP; tag
   `backend:"<harness>"`.
5. **Lane discipline** - telemetry to the collector only, never through aggregates.

The worked reference for a not-yet-wired harness is opencode, whose plugin-hook surface is
already designed (`docs/features/opencode-plugin-observability.md`, issue #51). A new harness
is onboarded by writing a `HarnessExporter` against that file's pattern. **PI specifically is
blocked on operator input** (section 8).

### 2.6 Surface preference order (one rule across all adapters)

When a harness offers multiple surfaces, prefer in this order, because it matches both
robustness against version drift and the proven-channel finding of the retro:
**(1) OTLP-native** (Gemini) where confirmed -> **(2) structured stream** (Codex `--json`,
Gemini `stream-json`, Claude `-p`) for orchestrated runs -> **(3) hooks** (Claude proven;
Codex/Gemini/opencode available) for in-process lifecycle -> **(4) session-log / rollout
tail** for interactive + backfill -> **(5) capture-pane scrape** as the last resort for
interactive TUIs with no machine surface (section 5). Claude is the exception where hooks ARE
the proven primary (retro, section 6) - so the order is a default, overridable per
`capabilities()`.

---

## 3. OTLP-SHAPED TOP LAYER (where the boundary sits)

### 3.1 The two-layer split

```
        ┌──────────────────────────────────────────────────────────────┐
 TOP    │  OTLP / collector integration surface  (the tidy contract)    │
 LAYER  │  POST /events (EventBatch), POST /v1/metrics, POST /v1/logs    │
        │  + an OTLP receiver (gRPC 4317 / http 4318) the workspace      │
        │    points harnesses at via OTEL_EXPORTER_OTLP_ENDPOINT          │
        └──────────────────────────────▲───────────────────────────────┘
   ====== BOUNDARY: above = standard OTLP/CollectedEvent; below = harness goo =====
        ┌──────────────────────────────┴───────────────────────────────┐
 BOTTOM │  Per-harness ExporterAdapters (section 2)                      │
 LAYER  │  Claude hooks | Codex --json + rollout/SQLite | Gemini OTLP/   │
        │  stream-json/JSONL | capture-pane scrape | future PI/opencode  │
        └────────────────────────────────────────────────────────────────┘
```

### 3.2 Why this boundary, and what already exists

The collector already exposes the clean top surface: `POST /events`
(`EventBatch`/`CollectedEvent`) plus native OTLP `POST /v1/metrics` and `POST /v1/logs`, all
converging through one dedup+store path (L1 section 2-3, `collector/routes.py:60-130`,
`otlp.py`). Gemini speaks standard OTLP and Claude speaks `claude_code.*` OTLP, so for those
the "adapter" can be as thin as pointing `OTEL_EXPORTER_OTLP_ENDPOINT` at the collector and
letting the existing OTLP parser map metric/log names to EventTypes.

**The boundary rule:** everything ABOVE the line is standard - OTLP wire format or the
`CollectedEvent` JSON - and is harness-independent. Everything BELOW is allowed to be a mess:
hook stdin parsing, SQLite cursors, `$set` journal folding, capture-pane regex. The adapter's
ONLY job is to cross that boundary, emitting either OTLP-JSON (for cost/token metrics, the only
channel carrying per-call `cost_usd`, L1 section 3) or `CollectedEvent` envelopes (for
lifecycle/tool events). The retro (section 6) is the reason OTLP is the *presentation* layer
and `/events` is the *load-bearing* one: OTLP parity could not be demonstrated landing, while
the hook->`/events` channel reliably does.

### 3.3 A generic OTLP normalizer is needed to finish the top layer

Today the OTLP parser is Claude-branded: `_METRIC_TO_EVENT_TYPE`/`_LOG_EVENT_TO_EVENT_TYPE`
key off `claude_code.*` (L1 section 6, `otlp.py:40-67`). Gemini emits `gemini_cli.*` and
`gen_ai.*`. To make OTLP a genuinely harness-agnostic top surface, the metric/log name maps
must become a registry keyed by provider prefix (`claude_code.` , `gemini_cli.`, `gen_ai.`),
not a hardcoded Claude dict. This is the single most valuable top-layer increment and is small.

---

## 4. THE MINIMAL SEAM IN agentic-primitives / syn137

### 4.1 Mirror the per-agent adapter registry that already exists

`interactive_tmux.py` already proves the pattern: a `_ADAPTERS = {"claude": _ClaudeAdapter,
"codex": _CodexAdapter, "gemini": _GeminiAdapter}` registry dispatched by agent name
(`lib/agentic-primitives/providers/workspaces/interactive-tmux/driver/interactive_tmux.py:543-547`),
where each adapter encodes per-agent quirks (submit pattern, init gates, `is_ready`
heuristic) behind a uniform shape (`:213-541`). The observability seam is the SAME shape,
one layer over: a `_EXPORTERS = {"claude": ClaudeExporter, ...}` registry of
`HarnessExporter` (section 2.1), dispatched by the same agent name.

This is deliberate: the interactive-tmux driver is already the place that knows "which agent
is in which pane," so it is the natural host for "which exporter scrapes which pane."

### 4.2 What new code is needed

1. **`HarnessExporter` protocol + `CanonicalEvent`/`CapabilitySet`** in
   `lib/agentic-primitives/lib/python/agentic_events/` (next to the existing `emitter.py` /
   `types.py` it already builds on, L1 section 1c). Pure data + mapping; no I/O.
2. **A `_EXPORTERS` registry** mirroring `_ADAPTERS`, plus a `select_surface(capabilities())`
   helper encoding the preference order of section 2.6.
3. **An `ExporterRunner`** that owns the two things the adapter must NOT: route selection
   (`/events` batch vs OTLP) and `context:{}` injection (section 4.3). One runner serves every
   adapter; it is where retry/batching live (reuse the existing collector client,
   `packages/syn-adapters/src/syn_adapters/collector/client*.py`, L4).
4. **A generic OTLP name registry** (section 3.3) replacing the Claude-only dict in `otlp.py`.

Nothing in `agent_events`, `AgentEvent.from_dict`, or the collector routes changes. The seam
is additive.

### 4.3 The harness-agnostic `context:{}` injection idea

The envelope already carries a free `context:{}` (L1 section 1c). The orchestrator/workspace -
the only layer that knows `execution_id`/`phase_id` - injects them into `context` (or as
top-level reserved keys) BEFORE the `ExporterRunner` ships the batch, exactly as the brief
specifies and as the hard constraint of section 1.5 requires. Concretely, the runner is
constructed with `{execution_id, phase_id}` from the orchestration context and stamps every
`CanonicalEvent` the adapter returns. The adapter stays ignorant of orchestration; the runner
stays ignorant of harness quirks. This mirrors how `interactive_tmux` already threads an
`_AdapterContext` (`interactive_tmux.py:195-211`) of runtime facts into per-agent adapters
without the adapters knowing where those facts came from.

### 4.4 Smallest first increment

**Increment 0 (ship first):** factor the EXISTING Claude hook path behind `HarnessExporter`
with a no-op `ExporterRunner` that uses the current `/events` route. Zero behavior change,
proves the interface against the one harness we KNOW lands rows (retro: hooks are the proven
channel). This is pure refactor + tests, no new capability, lowest risk.

---

## 5. INTERACTIVE vs -p (why one adapter shape serves both)

### 5.1 The two extraction modes

| | `claude -p` / `codex exec --json` / `gemini --output-format stream-json` | interactive-tmux (capture-pane) |
|---|---|---|
| Surface | structured JSONL on stdout, machine-readable | a rendered TUI; only `tmux capture-pane -p` text exists |
| Event source | parse each JSONL line (L1 Route B `parse_jsonl_events`; L2 `--json`; L3 stream-json) | scrape the pane buffer + readiness heuristics (`interactive_tmux.py:327-345` is_ready, `:175-177` capture) |
| Token/cost | carried in `result`/`turn.completed.usage`/`.stats` | NOT in the pane; must come from the session-log/rollout/transcript written to disk during the interactive run |
| Lifecycle | explicit `init`/`thread.started`/`result` events | inferred from pane-state transitions: launch -> `is_started` -> `is_ready` after a turn (`interactive_tmux.py:348-359`, `819-851`) |
| Timestamps | per-line (Claude) or receipt-stamped (Codex `--json` has none, L2) | receipt-stamped at scrape time |

### 5.2 The "event-capture arc" for the interactive path

The retro names this the "event-capture arc": in interactive mode the pane scrape gives you
lifecycle/turn boundaries (the `await_completion` ready transitions) but NOT tokens/tools-with-
args, which only exist in the on-disk session log the harness writes anyway (Claude transcript,
Codex rollout, Gemini chats JSONL). So the interactive adapter is a COMPOSITE:
**capture-pane for lifecycle + session-log tail for tokens/tools**, correlated by `session_id`.

### 5.3 Why ONE adapter shape serves both

The `HarnessExporter.normalize(raw)` signature is agnostic to where `raw` came from. A
`RawSignal` is just "a thing to map": a JSONL line from `-p`, a SQLite row from a rollout, OR a
captured pane frame. Both modes feed the SAME `normalize()` and produce the SAME
`CanonicalEvent` envelope; only the `capabilities()` result and the runner's polling loop
differ (stream reader vs pane poller + file tailer). The interactive-tmux driver already proves
adapters can absorb radically different mechanics (Claude two-step send vs Gemini Enter-only,
`interactive_tmux.py:319-324` vs `:512-515`) behind one interface; the exporter layer inherits
that property. This is why the design does not fork into "batch observability" and "interactive
observability" subsystems - it is one registry with per-harness, per-surface capability flags.

---

## 6. CROSS-LINK: the 2026-06-18 retro + open risks

### 6.1 What the retro established (verdict: inconclusive)

`experiments/2026-06-18--observability--interactive-tmux-otel-parity/verdict.md`:

- **C0 baseline FAILED** - even `claude -p` produced 0 `OTLP_*` rows in the dev stack; the
  baseline OTLP pipeline did not land the rows it was supposed to (verdict.md:12).
- **C1/C2 interactive turns never completed** - so the interactive OTLP/hook channel verdict is
  confounded, not proven absent (verdict.md:8-10).
- **C3 PASS** - collector network reachability was fine; HTTP 200 to `/v1/metrics` from inside
  the container (verdict.md:11). So the failure is wiring/extraction, not connectivity.
- **Conclusion (brief + verdict.md:14-15):** the proven channel is HOOK + SESSION-LOG +
  EXPORTER into `/events`; OTLP is a presentation layer on top, not yet demonstrated landing.

This is WHY the design (a) makes OTLP the top presentation layer and `/events` the load-bearing
route (section 3.2), (b) makes Increment 0 the already-proven Claude hook path (section 4.4),
and (c) puts `capabilities()` probing in the interface rather than assuming OTLP (section 2.6).

### 6.2 Open risks

1. **OTLP landing is unproven end-to-end** (retro). Do not gate any harness's "full
   observability" claim on OTLP until a green rerun exists; the floor is the hook/session-log
   minimal set (section 1.3).
2. **Two release gates from the retro remain open:** the baseline OTLP pipeline must be
   unblocked AND interactive workspace trust automation fixed before the OTLP-parity rerun is
   meaningful (verdict.md:15). These block the *top layer*, not the *adapter floor*.
3. **Gemini -> Antigravity migration** (L3 section 7): the recommended Gemini surface (OTLP +
   JSONL path) may not survive `agy`. `capabilities()` mitigates but the spike is owed.
4. **Codex has no native OTLP and no verified hook payload** (L2 section 8, OQ1): Codex obs
   leans on `--json` + rollout/SQLite, which is internal-schema-fragile and may leak sensitive
   prompts (L2 "Gaps"). Treat rollout as opaque; redact.
5. **Session-log schemas are version-fragile across all three** (Gemini `$set` journal,
   Codex rollout, even Claude transcript shape is hardcoded, L1 section 6). Tie adapters to a
   captured-fixture conformance test per harness version.
6. **Cost is computed, not observed, for Codex+Gemini** (L2/L3): a stale pricing table silently
   corrupts cost. The pricing table is an operational dependency, not a one-time constant.
7. **Capture-pane scraping is inherently brittle** - readiness heuristics already needed
   three-signal hardening (`interactive_tmux.py:327-345`); pane-derived lifecycle will lag and
   occasionally misfire. Keep it strictly last-resort (section 2.6) and always pair with the
   on-disk session log for the authoritative tokens/tools.

---

## 7. PHASED BUILD PLAN (smallest shippable adapter first)

| Phase | Deliverable | Surface(s) | Risk | Proves |
|---|---|---|---|---|
| **0** | Factor existing Claude hook path behind `HarnessExporter` + no-op `ExporterRunner` on `/events`. Capture-fixture tests. | Claude hooks | very low | the interface against the ONE proven-landing harness (retro). No behavior change. |
| **1** | `_EXPORTERS` registry + `ExporterRunner` (route selection + `context:{}` injection of execution_id/phase_id) wired into the interactive-tmux driver beside `_ADAPTERS`. | Claude | low | the seam (section 4); orchestrator correlation lands. |
| **2** | Codex adapter, Mode A (`codex exec --json` wrapper) + post-run `state_5.sqlite` join. | Codex structured stream + rollout | medium | second harness on the minimal event set (section 1.3); token normalization (1.4). |
| **3** | Gemini adapter via `--output-format stream-json` (orchestrated path). | Gemini stream-json | medium | third harness; `--session-id` pre-correlation. |
| **4** | Generic OTLP name registry (replace Claude-only dict, section 3.3) + Gemini OTLP receiver path for the interactive/user case. | OTLP top layer | medium-high | the tidy top surface for multiple providers. Gated on retro gate #2. |
| **5** | Interactive composite adapter: capture-pane lifecycle + session-log tail for tokens/tools (section 5.2), Codex Mode B + Gemini JSONL backfill. | capture-pane + session-log | high | interactive parity; closes the "event-capture arc". |
| **6** | Antigravity `agy` capability probe + adapter swap; PI adapter (once operator unblocks). | per capabilities() | high / blocked | future-harness generality (section 2.5). |

Each phase is independently shippable and adds at most one harness or one surface. The floor
(minimal event set) is reached for a harness at the END of its Phase; OTLP enrichment is always
a later, separately-gated add.

---

## 8. OPERATOR DECISIONS STILL NEEDED

1. **PI identity/access (BLOCKING for any PI work, L4 "Operator Input Needed").** What is "PI"
   (expand the acronym/name the product)? Install source + billing model? CLI binary + the
   `ntm` flag it should get? Which observability surface does it offer (structured stream /
   hooks / OTLP / none)? Until answered, PI gets the general pattern only, no adapter.
2. **Antigravity (`agy`) spike (BLOCKING for Gemini longevity, L3 section 7).** Authorize the
   1-hour spike on a real `agy` install to confirm (a) whether it emits OTLP, (b) the new JSONL
   path/schema, (c) the headless flag name. Decide whether to build the Gemini adapter against
   Gemini CLI now and accept a re-map, or wait for `agy`.
3. **Retro release gates (BLOCKING for the OTLP top layer, verdict.md:15).** Prioritize
   unblocking (a) the baseline OTLP pipeline and (b) interactive workspace trust automation,
   then schedule the OTLP-parity rerun. Decide whether the top layer ships before or after a
   green rerun (recommendation: ship the adapter floor first, OTLP after).
4. **Pricing table ownership (operational, L2/L3).** Codex and Gemini have no native dollar
   cost; cost is computed from tokens x model price. Who owns and refreshes the per-model
   pricing table, and where does it live?
5. **Prompt/PII redaction policy (L2/L3 "Gaps").** Rollout/transcript/`stream-json` can carry
   full prompts and model-visible context. Confirm whether prompt bodies are stored, previewed
   (the existing `prompt_preview <=200` convention, L1 1a), or stripped per harness.
6. **OTLP receiver protocol (L3 section 8).** Gemini OTLP defaults to gRPC @ `:4317`; the
   collector currently takes OTLP-JSON over HTTP. Decide whether to stand up a gRPC OTLP
   receiver or force `otlpProtocol=http` on every harness.
7. **Surface preference override per harness (section 2.6).** Confirm the default order
   (OTLP -> stream -> hooks -> session-log -> capture-pane), noting Claude's exception where
   hooks are primary. Operator may pin a different primary per harness for cost/reliability.

---

## Appendix - citation index

- Landing schema + normalizer: `packages/syn-adapters/src/syn_adapters/events/schema.py:67-86`,
  `.../events/models.py:226-262`, `:258-260` (execution_id/phase_id only-if-present).
- Collector enum values: `packages/syn-collector/src/syn_collector/events/types.py:68,69,75,76,84,114`.
- Collector routes / OTLP: `packages/syn-collector/src/syn_collector/collector/routes.py:60-130`,
  `.../collector/otlp.py:40-67`.
- Claude hooks/emitter/transcript: `lib/agentic-primitives/plugins/observability/hooks/handlers/observe.py:146-161,176`,
  `lib/agentic-primitives/lib/python/agentic_events/agentic_events/emitter.py:51-79`,
  `packages/syn-collector/.../watcher/transcript_parser.py:21-72`.
- Per-agent adapter registry to mirror: `lib/agentic-primitives/providers/workspaces/interactive-tmux/driver/interactive_tmux.py:543-547`
  (`_ADAPTERS`), `:195-211` (`_AdapterContext`), `:327-359` (readiness), `:819-851`/`:861-950`
  (lifecycle inference for the interactive path).
- Retro: `experiments/2026-06-18--observability--interactive-tmux-otel-parity/verdict.md:8-15`.
- opencode worked example: `docs/features/opencode-plugin-observability.md` (issue #51).
- Phase-1 inputs: `~/swarm-tasks/obs-L1..L4-*.md`.
</content>
</invoke>
