# Obs L5 Cross-Model Review

## VERDICT: SOUND-WITH-CHANGES

The design is directionally sound: per-harness extraction below a common observability sink is the right shape, and the existing `agent_events` table can carry a cross-harness normalized payload without a schema migration. But the design overstates landability in three places:

1. It says to target the collector enum, while the actual DB normalizer validates against `syn_shared.events.EventType`. Those vocabularies are not identical.
2. It treats the OTLP top layer as if a generic OTLP receiver already exists. The current collector only accepts OTLP JSON over FastAPI routes and only maps Claude metric/log names.
3. It stretches the `interactive_tmux.py` adapter registry analogy into the first increment. The registry is real, but observability should first be added at the existing orchestration stream/collector seam, not inside tmux pane driving.

## 1. Normalized Schema

The six-column target is real and sufficient for a first cross-harness design. `agent_events` is exactly `time, event_type, session_id, execution_id, phase_id, data`, with `session_id NOT NULL`, optional execution and phase columns, and JSONB payload (`packages/syn-adapters/src/syn_adapters/events/schema.py:67-75`). `AgentEvent.from_dict()` also does the expected flattening: timestamp fallback, `event_type`/`type`, remaining keys into `data`, and optional correlation IDs only if present (`packages/syn-adapters/src/syn_adapters/events/models.py:240-260`).

The event vocabulary claim needs correction. The design says adapters should emit `syn_collector.events.types.EventType` values, especially `session_ended`. That is unsafe. The collector enum has `SESSION_ENDED = "session_ended"` (`packages/syn-collector/src/syn_collector/events/types.py:67-69`), but `AgentEvent` imports its type from `syn_shared.events`, where the accepted lifecycle value is `SESSION_COMPLETED = "session_completed"` and the Literal union includes `session_completed`, not `session_ended` (`packages/syn-shared/src/syn_shared/events/__init__.py:21-25`, `:80-88`). The model maps Claude raw `result` to `SESSION_COMPLETED` (`packages/syn-adapters/src/syn_adapters/events/models.py:67-70`). A `/events` payload with collector-valid `session_ended` can therefore pass request validation and then fail or be skipped when persisted through `AgentEvent.from_dict()`.

Concrete fix: define the normalized event vocabulary from `syn_shared.events`, not from the collector enum, or first align the two enums. For the minimal set today, use `session_started`, `session_completed`, `tool_execution_started`, `tool_execution_completed`, `token_usage`, `cost_recorded`, and optionally `session_summary`. If the product wants `session_ended`, add it to `syn_shared.events`, projections, and compatibility mappings before adapters emit it.

The token keys also need to match existing projections. The current orchestration collector writes `cache_creation_tokens` and `cache_read_tokens` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ObservabilityCollector.py:126-138`), while the design proposes `cache_creation` and `cache_read`. Either standardize all new adapters on the current stored names or add projection support for aliases. Do not create a third vocabulary.

The session-id-only constraint is handled correctly in principle. Harnesses should not invent `execution_id` or `phase_id`. Existing code stamps correlation from orchestration context: `AgentExecutionHandler` passes `todo.execution_id` and `todo.phase_id` into `EventStreamProcessor` (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/AgentExecutionHandler.py:143-153`), `ObservabilityCollector` forwards them (`.../ObservabilityCollector.py:106-113`), and `record_observation()` applies them through `insert_one()` (`packages/syn-adapters/src/syn_adapters/events/store_helpers.py:165-170`). The design should say the runner must stamp them as top-level reserved fields before store insertion, not only bury them in `context`.

## 2. Per-Harness Adapters

Claude is feasible. Hooks, transcript parsing, and the existing stream processing are proven enough for a reference adapter. The main caveat is event-name compatibility: Claude hooks emit some names that differ from the DB vocabulary, so the adapter or runner must normalize before persistence.

Codex is feasible for orchestrated non-interactive runs via `codex exec --json`, with important reductions. The L2 evidence supports `thread.started`, `turn.completed.usage`, rollout JSONL, and `state_5.sqlite`. It does not prove full tool start/end from the live `--json` stream. Tool details are stronger in rollout `response_item` records, not necessarily in real-time stdout. The design should make Codex Phase 1 tokens/session-only from `--json`, then add rollout-based tool pairing by `call_id`. Do not claim full live tool lifecycle until a fixture proves `function_call` and `function_call_output` appear on the selected surface.

Gemini is feasible for headless `--output-format stream-json` and likely feasible for OTLP only after protocol work. L3 confirms Gemini CLI has OTLP-native docs and metrics, but the repo collector only exposes HTTP JSON `/v1/metrics` and `/v1/logs` handlers (`packages/syn-collector/src/syn_collector/collector/routes.py:53-91`). There is no gRPC receiver on 4317 in the checked code. `_wiring.py` only sets Claude telemetry env vars and a generic OTEL endpoint (`apps/syn-api/src/syn_api/_wiring.py:81-100`), not Gemini telemetry env/config. Gemini should start with `stream-json`; native OTLP should be a separate spike.

General/opencode is fine as a checklist only. PI is correctly blocked because L4 found no binary, flag, docs, or install. No concrete PI adapter should appear in the build plan until the operator identifies it.

Weakest adapter: interactive/capture-pane composite, not PI. PI is explicitly unknown, so it is not an adapter. Capture-pane lifecycle plus session-log tailing depends on brittle TUI readiness and multiple internal log schemas. The tmux driver itself documents strict, provider-specific readiness heuristics and stable-poll defenses (`lib/agentic-primitives/providers/workspaces/interactive-tmux/driver/interactive_tmux.py:327-345`, `:861-901`). Treat this as a late parity path, not part of the initial adapter floor.

## 3. The Seam

The `_ADAPTERS` analogy is partially valid but overextended. `interactive_tmux.py` really does have per-agent adapters for auth prep, launch, submit, readiness, and response markers (`lib/agentic-primitives/providers/workspaces/interactive-tmux/driver/interactive_tmux.py:195-220`, `:543-547`). That proves a registry pattern for TUI control quirks.

It does not prove that `interactive_tmux.py` is the natural home for observability exporters. Today the proven observability path for orchestrated runs is the execution stream and `ObservabilityCollector`, not pane capture. The existing code already has a Lane 2 collector that stamps session, execution, phase, workspace, and model (`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ObservabilityCollector.py:66-80`). A cross-harness exporter should plug first into the orchestration execution handler or stream processor boundary, where raw structured stdout exists.

Concrete fix: keep the `HarnessExporter` protocol, but place the first runner beside `EventStreamProcessor`/`AgentExecutionHandler`, not in `interactive_tmux.py`. Add a tmux exporter later that consumes `capture_response()` and session logs. This preserves the registry idea without coupling the clean path to the brittle interactive path.

The proposed "Increment 0" is not the smallest shippable thing because factoring existing Claude hooks behind a new protocol in `agentic-primitives` adds abstraction without exercising cross-harness behavior or fixing the known enum mismatch. The smallest useful increment is a fixture-tested canonical-event normalizer and store-path test that proves one canonical event batch lands in `agent_events` using the real accepted vocabulary.

## 4. OTLP Top Layer

The two-layer boundary is conceptually coherent: `/events` and OTLP-ish ingestion above, harness-specific extraction below. But the implementation claims need to be downgraded.

The repo has OTLP JSON routes, not a general OTLP receiver. The routes call `request.json()` and parse JSON payloads (`packages/syn-collector/src/syn_collector/collector/routes.py:60-79`). The metric/log mapping is hardcoded to Claude names: `claude_code.token.usage`, `claude_code.cost.usage`, `claude_code.session.count`, `claude_code.commit.count`, and Claude log event names (`packages/syn-collector/src/syn_collector/collector/otlp.py:39-67`). Gemini's default gRPC endpoint and `gemini_cli.*`/`gen_ai.*` names will not land through this as-is.

Concrete fix: state that OTLP is a future presentation/integration layer with two prerequisites: a protocol decision, either force HTTP JSON where each harness supports it or add a real OTLP gRPC receiver, and a provider-name registry for Claude, Gemini, and GenAI semantic conventions. Until the 2026-06-18 retro gates are green, `/events` with `CollectedEvent` is the load-bearing path.

## 5. Over/Under-Engineering and Missing Risks

Over-engineering risk: `CapabilitySet`, `HarnessExporter`, `ExporterRunner`, `_EXPORTERS`, `select_surface()`, and generic OTLP registry are a lot before a second harness lands one row. Keep the protocol minimal: `normalize(raw, context) -> list[CanonicalEvent]` plus fixture tests. Add capability probing only when one harness actually has two competing implemented surfaces.

Under-engineering risk: event identity and dedup are underspecified. `/events` requires `event_id` and uses it for dedup (`packages/syn-collector/src/syn_collector/collector/routes.py:107-120`). Deterministic hash over `session_id + event_type + timestamp + content` is not stable enough when adapters receipt-stamp events, replay rollout files, or receive cumulative token totals. Use source-native IDs and offsets where possible: Codex `thread_id + rollout_path + byte_offset` or `call_id`, Gemini session file line/message id/tool id, Claude hook timestamp plus hook name plus tool id. Include `source`, `backend`, `surface`, `schema_version`, and `sequence`/`offset` in `data`.

Ordering is also missing. `agent_events` has no sequence column, only time. Codex `--json` lacks timestamps per L2, and capture-pane events are receipt-stamped. Tool start/end pairing needs explicit `tool_use_id`/`call_id` and per-source sequence to avoid relying on time ordering.

Token accounting needs a stronger rule. Codex has per-turn and cumulative usage; Gemini metrics may be counters; Claude has session summaries. Store `usage_scope = "turn" | "session_total" | "cumulative_counter"` and `source_of_truth = "stream" | "rollout" | "otlp" | "summary"`. Make projections dedupe or replace cumulative totals rather than summing everything.

Backend tagging is necessary but should be top-level in `data` consistently: `provider`, `backend`, `surface`, `model`, `harness_version`, and `adapter_version`. The current design mentions `backend` only in the general checklist.

Security/redaction needs to be a hard requirement. Codex rollout, Gemini JSONL, and tool outputs can contain prompts, secrets, file contents, and MCP data. Existing `record_observation()` strips reserved keys but not sensitive payloads (`packages/syn-adapters/src/syn_adapters/events/store_helpers.py:146-160`). Adapters must preview, bound, and redact before writing.

## Single Highest-Risk Assumption

The highest-risk assumption is that "canonical `CollectedEvent` values that pass the collector enum will land cleanly in `agent_events`." They may not. The collector enum and `syn_shared.events` are currently divergent, especially `session_ended` versus `session_completed`, and persistence validates through `AgentEvent.from_dict()` against `syn_shared.events`. Fix the event vocabulary contract before building adapters on top.

## Tightened Smallest-First Increment

Ship this first:

1. Define `CanonicalAgentEvent` in the Syn code path that targets `syn_shared.events` values, not the collector enum. Include `session_id`, `event_type`, `timestamp`, `data`, `event_id`, and optional top-level `execution_id`/`phase_id`.
2. Add fixture tests that send representative `session_started`, `session_completed`, `tool_execution_started`, `tool_execution_completed`, and `token_usage` events through the real `/events` to `AgentEvent.from_dict()` path and assert the final insert tuple fields.
3. Add a tiny Codex `exec --json` normalizer for `thread.started` and `turn.completed.usage` only. Stamp execution and phase in the runner, include `provider="codex"`, `surface="exec-json"`, `usage_scope="turn"`, and a deterministic event id from `thread_id + stream_index + type`.
4. Only after that, add rollout tool pairing and Gemini `stream-json`. Leave OTLP registry and capture-pane composite out of the first shippable slice.

This proves the actual cross-harness contract with the least new machinery: one non-Claude harness, one structured surface, the real store vocabulary, and the real correlation stamping path.
