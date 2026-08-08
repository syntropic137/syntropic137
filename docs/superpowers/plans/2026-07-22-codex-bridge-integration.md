# Codex Bridge Integration - reuse the proven docker-exec + observability pipeline

> Status: implementation plan (buildable). Scope: the DAYS-AWAY OpenAI demo vertical
> slice. Explicitly NOT the agentic-primitives `itmux run` / `run_agent` / AP
> RunExecutor path (that is syn137#778, the ~2-week "build-it-right" target, OUT OF
> SCOPE here).

> **MODEL CORRECTION (2026-07-23, owner):** target the CURRENT codex model (GPT-5.6),
> NOT `gpt-5.1-codex`. Wherever this plan says `gpt-5.1-codex`, read "the current codex
> model". Per must-fix #3 the parser captures the ACTUAL model codex reports at runtime
> and uses that for telemetry + pricing, so the label stays honest regardless. The
> pricing-table entry is for the current codex model; exact input/output/cached rates
> are a `TODO(confirm-openai-pricing)` and do not block the demo working (only cost-label
> accuracy). Do not spend effort on 5.1.

## Goal

Run **codex** as a sibling programmatic harness inside a single Syntropic137 workflow
phase, producing a **real dashboard observability timeline** (tokens / cost / tool-ops
streamed live), by REUSING the exact machinery that already runs `claude -p`:

- the Docker workspace (`WorkspaceService`, `claude-cli`/hardened backend),
- `ManagedWorkspace.stream(cmd, ...)` (which runs an ARBITRARY argv via `docker exec -i`),
- the Processor To-Do List chain (`WorkflowExecutionProcessor`: PROVISION_WORKSPACE →
  RUN_AGENT → COLLECT_ARTIFACTS → COMPLETE_PHASE) - **unchanged**,
- the Lane-2 recorder (`ObservabilityCollector`) and its `SessionCostProjection` →
  dashboard timeline,
- ADR-024 setup-phase secret injection (how `~/.codex/auth.json` reaches the container).

The bridge adds, and ONLY adds: a codex command builder, a codex `--json` stream parser
that feeds the SAME `ObservabilityCollector`, codex pricing, codex auth injection, and a
provider selector that routes a phase to the codex harness. Existing `claude` and
`claude-interactive` phases are **behaviorally identical** - the wiring gains a command
dispatcher and `AgentExecutionHandler` gains a `runner` branch, and regression tests prove
the built command + recorded events for claude phases are unchanged (not a literal
"no edits" claim).

## Architecture

### The reuse map (verified against real code)

| Concern | Existing (claude) | Bridge (codex) | Change kind |
|---|---|---|---|
| Docker workspace + `docker exec` stream | `ManagedWorkspace.stream()` → `AgenticStreamAdapter` (`docker exec -i -w /workspace ... <argv>`) | **reused as-is** - `stream()` runs any argv | none |
| To-Do processor chain | `WorkflowExecutionProcessor._drain_todo_list` | **reused as-is** | none |
| Command builder | `_wiring._build_claude_command(phase, prompt) -> list[str]` | new `_build_codex_command`; dispatch by `provider` | new + dispatch |
| Stream parser | `EventStreamProcessor` (stream-json) | new `CodexStreamProcessor` (`--json`) sibling | new sibling |
| Lane-2 recorder | `ObservabilityCollector.record_tool_started/completed/token_usage/session_summary` | **reused as-is** by the codex parser | none |
| Cost | `total_cost_usd` from claude `result` event | estimate from codex `turn.completed.usage` × codex pricing (labeled estimated) | pricing table + estimate |
| Auth | ADR-024 setup phase injects OAuth/API key | setup phase writes `~/.codex/auth.json` (0600) | new secret field |
| Provider selection | `AgentConfiguration.provider ∈ {claude, claude-interactive}` | add `codex`; docker path, codex harness | Literal + validation |

### Key facts established by reading the code

1. **`ManagedWorkspace.stream()` runs an arbitrary command.** It delegates to
   `self._service._event_stream.stream(handle, command, ...)`. The production adapter
   (`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/stream_adapter.py`)
   builds `["docker","exec","-i","-w",wd, *env_flags, container, *command]`
   (`stream_helpers._build_exec_command`) and runs it via
   `asyncio.create_subprocess_exec(*exec_cmd, stdout=PIPE, stderr=STDOUT)` - **stdin is
   NOT set**, so the docker-exec subprocess **inherits syn-api's stdin** and `-i` keeps it
   open. There is **no `sh -c`**, args are passed individually, so
   `codex exec --json ... "<prompt>"` runs with the prompt as a single argv element.
   Codex takes the prompt from argv and should not read stdin, but an inherited-open stdin
   is a hang risk under `-i`. Task 10 (must-fix #7) sets
   `stdin=asyncio.subprocess.DEVNULL` on the non-interactive stream path (after proving
   `claude -p` is unaffected) so codex cannot block on stdin.

2. **`ManagedWorkspace.interrupt()` is claude-hardcoded.** `interrupt_container` runs
   `docker exec <c> sh -c "PID=$(pgrep -n claude) && kill -INT $PID"`
   (`managed_workspace_ops._send_sigint`). `pgrep -n claude` never matches `codex exec`, so
   cancellation of a codex phase is a no-op today. Task 11 (must-fix #4) makes interrupt
   process-aware so codex phases are actually cancellable.

2. **`AgentExecutionHandler` non-interactive branch** builds an `EventStreamProcessor`
   and calls `processor.process_stream(workspace.stream(claude_cmd, ...), workspace)`,
   then reports `AgentExecutionCompletedCommand`. The `provider="claude-interactive"`
   branch is a separate code path (`interactive_prompt is not None`) and is NOT touched.

3. **`provider` already selects the path.** `WorkflowExecutionProcessor._workspace_service_for`
   only diverts `provider == "claude-interactive"` to the tmux service; every other value
   (including a new `"codex"`) stays on the default Docker service.
   `WorkspaceProvisionHandler._is_interactive_phase` returns `False` unless provider is
   `claude-interactive`, so `codex` takes the docker `claude_cmd` path. Both selectors
   therefore need **no change** for codex - codex rides the docker path for free.
   (This is a behavioral guarantee to test, NOT a "byte-for-byte unchanged" claim: the
   wiring layer gains a command dispatcher and `AgentExecutionHandler` gains a `runner`
   branch. The guarantee is: for `provider ∈ {claude, claude-interactive}` the built
   command and recorded events are IDENTICAL to today, proven by regression tests, not by
   the absence of edits.)

4. **The cost model-passing bug (trap, must-fix #9).** `SessionCostProjection._handle_token_usage`
   (line 184) and `TimescaleSessionCostQuery._calculate_cost` (line 144) both call
   `CostCalculator.calculate_token_cost(...)` **without `model=`**, so
   `get_model_pricing("")` falls through to `DEFAULT_MODEL_ID` = Sonnet. For claude this
   is masked because `on_session_summary` overwrites with the SDK `total_cost_usd`. For
   codex there is no SDK cost, so interim AND final token-derived cost would be
   Sonnet-priced unless: (a) we thread `model` through both read paths (Timescale must
   resolve `agent_model` via `_resolve_agent_model` BEFORE calling `_calculate_cost`);
   (b) the codex parser computes its estimate through the STRICT
   `resolve_model_pricing(model)` (which returns `None` on unknown, forcing a
   mark-unavailable instead of a silent Sonnet default) - NOT through `calculate_cost()`,
   which still defaults to Sonnet; and (c) the parser emits an authoritative
   `total_cost_usd` estimate that short-circuits pricing on both read paths
   (`_SESSION_SUMMARY_QUERY.sdk_cost` and `on_session_summary.total_cost_usd`).

5. **`agent-net` allows broad direct egress (egress fear DEBUNKED).**
   `docker/docker-compose.yaml` line 244-245: `agent-net` is **NOT `internal: true`**
   ("agents need egress for git operations"). Agent containers get no `HTTP(S)_PROXY`
   forced on them, and `SecurityPolicy.allowed_hosts` is **not network-enforced by the
   docker provider**. So `codex exec` reaches `api.openai.com` directly TODAY with no
   networking change. Only Envoy-*routed* Anthropic traffic uses the sidecar; codex egress
   is direct. See Task 8 / the networking note for what a future hardening would require.

6. **Codex `--json` schema** (grounded in
   `lib/agentic-primitives/plugins/delegation/skills/delegating-to-codex/SKILL.md` and a
   real 2026-06-08 capture): JSONL, one event per line -
   `thread.started{thread_id}`, `turn.started`, `item.started`/`item.completed`
   with `item.type ∈ {agent_message, command_execution{command,aggregated_output,exit_code,status}, file_change}`,
   and `turn.completed{usage{input_tokens,cached_input_tokens,output_tokens,reasoning_output_tokens}}`.
   In the real capture, `input_tokens=237408` **includes** `cached_input_tokens=202112`;
   so fresh input = `input_tokens - cached_input_tokens`, cache_read = `cached_input_tokens`,
   billable output = `output_tokens + reasoning_output_tokens`. `usage` appears **only in
   `turn.completed`** (per turn) and no USD figure surfaces under ChatGPT-subscription auth.

7. **Codex is NOT in the default `claude-cli` workspace image.** Only the
   `interactive-tmux` image installs `@openai/codex@0.139.0`. The default image
   (`lib/agentic-primitives/providers/workspaces/claude-cli/Dockerfile`) must gain codex,
   built via the staged flow `uv run scripts/build-provider.py claude-cli` (NOT a raw
   `docker build` from the provider dir - the build stages wheels/plugins first).
   `/home/agent` is tmpfs-backed at runtime (image bakes are wiped), so `~/.codex` must be
   created at RUNTIME by the setup script; the codex npm binary installs globally to
   `/usr/local` and survives the tmpfs mount.

### Field decision: extend `provider`, do NOT reuse `agent_id`

`agent_id ∈ {claude,codex,gemini}` already exists, but it selects **which tmux pane** in
the interactive-tmux backend and is *ignored by the docker path*. Reusing it to also pick
the docker harness creates contradictory combos (e.g. `provider=claude, agent_id=codex` -
"claude provider but codex harness"?). Instead, extend the one field that already means
"which harness/path":

- `AgentYamlDefinition.provider: Literal["claude","claude-interactive","codex"]`.
- `provider="codex"` ⇒ docker workspace (same backend as `claude`) + codex command builder
  + codex parser. `agent_id` stays irrelevant for the docker path (as it already is for
  `provider="claude"`).
- **The `agent_id` invariant (must-fix #8):** `_build_agent_config_from_phase` fills
  `agent_id` from the domain default `"claude"` when YAML omits it, so a codex phase
  silently reads `AgentConfiguration(provider="codex", agent_id="claude")` - misleading.
  Two mirrors carry `AgentConfiguration`:
  `packages/syn-domain/.../aggregate_execution/value_objects.py` (line 52) AND
  `packages/syn-domain/.../_shared/ExecutionValueObjects.py` (line 33). Fix BOTH: change
  the `agent_id` default to `None` (Optional) so "unset" is distinguishable from "claude",
  and treat `agent_id is None` as "not a tmux-pane selection" on the docker path. The
  interactive-tmux path already coerces `None` to `"claude"` at its own boundary
  (`_provisioned_agents`), so this stays back-compatible.
- **Dispatch strictly by `provider`.** The harness `runner` is derived ONLY from
  `phase.agent_config.provider` (`"codex"` ⇒ codex, else claude). No fallback to
  `agent_id`. This keeps `claude` / `claude-interactive` phases behaviorally identical.
- Validation (Task 6): reject `provider="codex"` combined with an explicit
  `agent_id`/`claude-interactive` that would contradict it. One field = one decision.

### Two-lane compliance

Lane 1 (domain) is untouched: the aggregate still receives `AgentExecutionCompletedCommand`
with token counts and an `exit_code`. Lane 2 (telemetry): the codex parser writes ONLY to
`ObservabilityCollector` (tool ops, per-turn token usage, session summary). No aggregate
sees telemetry. Restart-safety is inherited from the unchanged processor chain.

## Tech Stack

- Python 3.14, `uv` workspaces, strict pyright (no `Any` in new code), Pydantic v2 models
  (`frozen=True`, `extra="forbid"` at YAML boundary).
- `codex` CLI `@openai/codex@0.139.0` (npm) inside the workspace container.
- Docker Compose dev stack (`just dev`, API on port 8137), TimescaleDB observability,
  MinIO artifacts/conversations, Redis control signals.
- Tests: `pytest` (unit + recording-playback), dev-stack e2e.

## Global Constraints

- Strict typing; **no `Any`** in new code (JSON-boundary dicts use `dict[str, object]` and
  are narrowed immediately; the existing `EventStreamProcessor` uses `dict[str, Any]` at
  the JSONL seam with an inline justification - the codex parser mirrors that single
  documented seam only).
- **No em dashes** anywhere (hyphens only).
- Pin exact `==` dep versions in app `pyproject` (no new Python deps expected; codex is a
  container-side npm dep pinned in the Dockerfile).
- `just fitness-check` (cognitive/cyclomatic gates) and `just docs-sync` (codegen drift)
  clean before every PR. New API routes (none expected here) must use Pydantic response
  models.
- Secrets: `~/.codex/auth.json` mode `0600`; codex auth **never** in argv, logs, events,
  or commits. Canonical env-var name reused across resolver + Pydantic + generated env +
  1Password field.
- Keep `claude` / `claude-interactive` phases behaviorally identical (dispatch strictly by
  provider; regression tests assert identical built command + recorded events); mixed-
  workflow back-compat tests required.

---

## File Structure

New (N) and changed (C) files, exact paths:

```
packages/syn-shared/src/syn_shared/pricing/__init__.py                                   (C) codex models + no-sonnet-default guard + is_estimated
packages/syn-shared/src/syn_shared/pricing/test_pricing_codex.py                         (N) unit tests
packages/syn-shared/src/syn_shared/settings/config.py                                    (C) codex_auth_json: SecretStr | None
packages/syn-shared/src/syn_shared/settings/constants.py                                 (C) ENV_CODEX_AUTH_JSON
packages/syn-shared/src/syn_shared/env_constants.py                                      (C) ENV_CODEX_AUTH_JSON re-export
scripts/op_env_export.py                                                                  (C) add ENV_CODEX_AUTH_JSON to _KEYS

apps/syn-api/src/syn_api/_wiring.py                                                       (C) _build_codex_command + _build_agent_command dispatch

packages/syn-domain/.../execute_workflow/CodexStreamProcessor.py                          (N) codex --json -> ObservabilityCollector
packages/syn-domain/.../execute_workflow/test_codex_stream_processor.py                   (N) recording-playback tests
packages/syn-domain/.../execute_workflow/recordings/codex_multiturn.jsonl                 (N) real captured MULTI-turn codex --json output
packages/syn-domain/.../execute_workflow/recordings/codex_malformed.jsonl                 (N) hand-crafted malformed-line fixture
packages/syn-domain/.../execute_workflow/recordings/codex_no_terminal.jsonl               (N) hand-crafted no-turn.completed fixture
packages/syn-domain/.../execute_workflow/handlers/AgentExecutionHandler.py                (C) runner param -> parser selection
packages/syn-domain/.../execute_workflow/processor_types.py                               (C) AgentHandlerProtocol.handle gains runner
packages/syn-domain/.../execute_workflow/WorkflowExecutionProcessor.py                     (C) derive+pass runner in _handle_run_agent
packages/syn-domain/.../execute_workflow/handlers/WorkspaceProvisionHandler.py             (C) skip claude plugin-dirs for codex
packages/syn-domain/.../execute_workflow/test_codex_bridge_e2e.py                          (N) mixed-workflow back-compat + codex phase

packages/syn-domain/.../_shared/workflow_definition.py                                     (C) provider Literal += codex + validation
packages/syn-domain/.../aggregate_workflow_template/value_objects.py                       (C) provider docstring (str, no structural change)
packages/syn-domain/.../aggregate_execution/value_objects.py                               (C) AgentConfiguration.agent_id default None (invariant, #8)
packages/syn-domain/.../_shared/ExecutionValueObjects.py                                    (C) AgentConfiguration.agent_id default None (mirror, #8)
packages/syn-domain/.../execute_workflow/processor_types.py                                 (C) Runner Literal type + AgentHandlerProtocol.handle(runner)

packages/syn-adapters/.../workspace_backends/agentic/stream_adapter.py                      (C) stdin=DEVNULL on non-interactive stream (#7)
packages/syn-adapters/.../workspace_backends/agentic/test_stream_adapter.py                 (C) stdin regression test
packages/syn-adapters/.../workspace_backends/service/managed_workspace_ops.py                (C) process-aware interrupt (codex) (#4)
packages/syn-adapters/.../workspace_backends/service/managed_workspace.py                    (C) pass agent process hint to interrupt (#4)
packages/syn-adapters/.../workspace_backends/service/test_interrupt.py                       (N) codex interrupt test

packages/syn-adapters/.../workspace_backends/service/setup_phase_secrets.py                (C) codex_auth_json field + build_setup_script + _resolve_codex_credentials
packages/syn-adapters/.../workspace_backends/service/setup_phase.py                         (C) (no env var for codex auth; file-only via setup script)
packages/syn-adapters/.../workspace_backends/service/test_setup_phase_secrets.py            (C) codex auth injection tests

packages/syn-domain/.../agent_sessions/slices/session_cost/projection.py                   (C) pass model to calculate_token_cost (bug-class fix)
packages/syn-domain/.../agent_sessions/slices/session_cost/timescale_query.py               (C) pass model to calculate_token_cost (bug-class fix)
packages/syn-domain/.../agent_sessions/slices/session_cost/test_cost_model_resolution.py     (N) regression tests

lib/agentic-primitives/providers/workspaces/claude-cli/Dockerfile                           (C, SUBMODULE) install @openai/codex@0.139.0

workflows/demo/codex-bridge-demo.yaml                                                        (N) demo workflow (single codex phase)
docs/adrs/ADR-0XX-codex-bridge.md                                                             (N) short ADR recording the reuse decision
```

---

## Task 1 - Codex pricing + no-sonnet-default guard (pure, unit-testable)

**Why first (off critical path but zero deps):** everything downstream that computes cost
needs a real codex entry, and the sonnet-default trap must be closed.

**Files:** `packages/syn-shared/src/syn_shared/pricing/__init__.py`,
`packages/syn-shared/src/syn_shared/pricing/test_pricing_codex.py`.

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `MODEL_PRICING_TABLE["gpt-5.1-codex"] = ModelPricing(model_id="gpt-5.1-codex",
    input_per_million=Decimal("15.00"), output_per_million=Decimal("60.00"),
    cache_creation_per_million=Decimal("15.00"), cache_read_per_million=Decimal("1.50"))`.
    **input $15/1M, output $60/1M** are grounded in `providers/models/openai/gpt-codex.yaml`.
    **The `1.50` cached-input rate (0.1x input) is an ASSUMPTION** - it is NOT in the model
    YAML. Source it from OpenAI's published cached-input pricing for the model at
    implementation time; if unconfirmed, encode it as a named constant
    `_CODEX_CACHED_INPUT_MULTIPLIER = Decimal("0.10")` with a `# TODO(#<issue>): confirm`
    comment and a test asserting the multiplier is applied, so the assumption is explicit
    and reviewable (not buried in a literal).
  - `MODEL_ALIASES["codex"] = "gpt-5.1-codex"`, `MODEL_ALIASES["gpt-codex"] = "gpt-5.1-codex"`,
    `MODEL_ALIASES["gpt-5.1-codex"] = "gpt-5.1-codex"` (identity for safety).
  - `CODEX_MODEL_IDS: frozenset[str] = frozenset({"gpt-5.1-codex"})` and
    `def is_estimated_cost(model_id: str) -> bool` returning `True` for codex family
    (labels the timeline "estimated").
  - New `def resolve_model_pricing(model_id: str) -> ModelPricing | None` that resolves
    aliases + exact + prefix match but returns **`None`** instead of silently defaulting to
    Sonnet, so callers that know the model MUST handle the unknown case. `get_model_pricing`
    keeps its default fallback for legacy back-compat. **The codex path (Task 3) MUST use
    `resolve_model_pricing`** and mark cost unavailable on `None`, never `calculate_cost()`.

**Steps (TDD):**

1. Write failing test `test_pricing_codex.py`:
   ```python
   from decimal import Decimal
   from syn_shared.pricing import (
       get_model_pricing, resolve_model_pricing, is_estimated_cost, calculate_cost,
   )

   def test_codex_alias_resolves_to_codex_not_sonnet():
       p = get_model_pricing("codex")
       assert p.model_id == "gpt-5.1-codex"
       assert p.input_per_million == Decimal("15.00")
       assert p.output_per_million == Decimal("60.00")

   def test_codex_api_name_resolves():
       assert get_model_pricing("gpt-5.1-codex").model_id == "gpt-5.1-codex"

   def test_unknown_model_returns_none_from_strict_resolver():
       assert resolve_model_pricing("totally-unknown-model") is None
       # back-compat helper still defaults, but strict resolver does not
       assert get_model_pricing("totally-unknown-model").model_id == "claude-sonnet-4-20250514"

   def test_codex_cost_is_flagged_estimated():
       assert is_estimated_cost("gpt-5.1-codex") is True
       assert is_estimated_cost("claude-sonnet-4-20250514") is False

   def test_codex_cost_math_no_double_count():
       # fresh input 35_296, cache_read 202_112, output 1_273 (1139 + 134 reasoning)
       cost = calculate_cost(35_296, 1_273, model="gpt-5.1-codex", cache_read=202_112)
       expected = (Decimal(35_296)*Decimal("15.00")
                   + Decimal(1_273)*Decimal("60.00")
                   + Decimal(202_112)*Decimal("1.50")) / Decimal("1_000_000")
       assert cost == expected

   def test_cached_input_multiplier_is_explicit():
       from syn_shared.pricing import _CODEX_CACHED_INPUT_MULTIPLIER, MODEL_PRICING_TABLE
       p = MODEL_PRICING_TABLE["gpt-5.1-codex"]
       assert p.cache_read_per_million == p.input_per_million * _CODEX_CACHED_INPUT_MULTIPLIER

   def test_legacy_unknown_model_still_defaults_but_strict_does_not():
       # legacy callers (claude interim) keep the default; strict resolver forces a decision
       assert get_model_pricing("some-legacy-alias").model_id == "claude-sonnet-4-20250514"
       assert resolve_model_pricing("some-legacy-alias") is None
   ```
   Run: `uv run pytest packages/syn-shared/src/syn_shared/pricing/test_pricing_codex.py -q` → fails.
2. Implement table + aliases + `resolve_model_pricing` + `is_estimated_cost` + `CODEX_MODEL_IDS`;
   export in `__all__`.
3. Run the same command → green.
4. `uv run ruff check packages/syn-shared/src/syn_shared/pricing && uv run ruff format --check packages/syn-shared/src/syn_shared/pricing`.
5. Commit: `feat(pricing): add gpt-5.1-codex pricing + strict resolver (no sonnet default)`.

---

## Task 2 - Cost model-resolution bug-class fix (projection + timescale query)

**Why:** closes the "every token event priced as Sonnet" trap on BOTH read paths. Fix the
whole bug class together (feedback_no_out_of_scope_shortcuts).

**Files:**
`packages/syn-domain/.../agent_sessions/slices/session_cost/projection.py`,
`.../session_cost/timescale_query.py`,
`.../session_cost/test_cost_model_resolution.py` (N).

**Interfaces:**
- `SessionCostProjection._handle_token_usage`: pass `model=data.get("model")` into
  `self._cost_calculator.calculate_token_cost(...)` (data already carries `model`, stamped
  by `ObservabilityCollector.record_token_usage`).
- `TimescaleSessionCostQuery._calculate_cost`: accept the resolved `agent_model`
  (`_resolve_agent_model(exec_result, token_result)`) and pass it into
  `calculate_token_cost(model=agent_model)`.

**Steps (TDD):**

1. Failing test `test_cost_model_resolution.py`:
   ```python
   from decimal import Decimal
   from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator

   def test_token_cost_uses_passed_model():
       calc = CostCalculator()
       codex = calc.calculate_token_cost(1000, 1000, model="gpt-5.1-codex")
       sonnet = calc.calculate_token_cost(1000, 1000, model="claude-sonnet-4-20250514")
       assert codex != sonnet
       assert codex == (Decimal(1000)*Decimal("15.00") + Decimal(1000)*Decimal("60.00")) / Decimal("1_000_000")
   ```
   Plus a projection-level test that feeds a `TOKEN_USAGE` observation with
   `data={"input_tokens":1000,"output_tokens":1000,"model":"gpt-5.1-codex"}` through a
   `SessionCostProjection` with an in-memory store and asserts
   `session_cost.total_cost_usd` equals codex pricing (not sonnet).
   Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/agent_sessions/slices/session_cost/test_cost_model_resolution.py -q` → fails on the projection test.
2. Implement the two one-line `model=` threads.
3. Run → green. Then run the existing session_cost suite to prove claude unaffected:
   `uv run pytest packages/syn-domain/src/syn_domain/contexts/agent_sessions/slices/session_cost -q`.
4. Lint/format; commit: `fix(cost): resolve per-model pricing on both read paths (was sonnet-defaulting)`.

---

## Task 3 - CodexStreamProcessor (`--json` -> ObservabilityCollector), recording-playback

**Why:** the core of the bridge. Produces the live dashboard timeline for codex by
feeding the SAME `ObservabilityCollector`.

**Decision - sibling processor, not a full Strategy refactor (justified):** the task
recommends a Strategy split of `EventStreamProcessor` (shared cancel-poll/accumulation
loop). The outer loop is ~40 lines (`process_stream`) and the claude parser is battle-
tested. Days before a demo, refactoring that shared loop risks regressing every existing
claude phase and fights `just fitness-check` churn. So: implement a **standalone
`CodexStreamProcessor`** that REUSES `TokenAccumulator`, `ObservabilityCollector`,
`StreamResult`, and `CancelSignalPoller`, and mirrors only the thin outer loop. The claude
`EventStreamProcessor` is left untouched (claude path behaviorally identical). Post-demo
cleanup: extract a shared `_StreamConsumer(cancel_poll + line loop + StreamResult)` with a
per-provider `LineHandler` (tracked as a follow-up issue). This keeps each class small and
under the complexity gates.

**Files:** `CodexStreamProcessor.py` (N), `test_codex_stream_processor.py` (N),
`recordings/codex_multiturn.jsonl` (N, captured in step 0) plus `codex_malformed.jsonl`
and `codex_no_terminal.jsonl` (N, hand-crafted).

**Interfaces:**
- Consumes:
  - `stream: AsyncIterator[str]` (from `workspace.stream(codex_cmd, ...)`),
  - `workspace: InterruptibleWorkspace` (reused Protocol from `EventStreamProcessor`),
  - collaborators via constructor: `tokens: TokenAccumulator`, `collector: ObservabilityCollector`,
    `controller: ExecutionController | None`, `execution_id/phase_id/session_id: str`,
    `agent_model: str` (the codex model id, e.g. `gpt-5.1-codex`).
- Produces: `async def process_stream(stream, workspace) -> StreamResult` - the SAME
  `StreamResult` dataclass, with:
  - `total_cost_usd` = codex pricing estimate over summed tokens via strict
    `resolve_model_pricing(agent_model)`; **`None` (cost unavailable, not $0) if the model
    is unknown** - never a Sonnet default,
  - `result_input_tokens/result_output_tokens/result_cache_read` = summed authoritative
    totals derived from `turn.completed.usage`,
  - `num_turns` = count of `turn.completed`,
  - `conversation_lines` = the RAW codex JSONL lines (provider-native, NOT claude-shaped),
    stored as-is so `ConversationRecorder` persists the codex transcript. Downstream
    conversation readers must tolerate provider-native JSONL (note in the ADR + a
    `test_conversation_recorder` case that a codex line round-trips without assuming claude
    keys),
  - `error_reason` set on: malformed JSON that cannot be parsed as codex events, a stream
    that ends WITHOUT any `turn.completed` (no authoritative usage), or a non-zero
    `command_execution.exit_code` recorded for operator visibility. See "Exit + failure
    semantics" below - an inner command failure is a failed TOOL op, not automatically a
    failed run.
- **Updates the shared `TokenAccumulator`** (`self._tokens.record(...)`) on every
  `turn.completed`, in ADDITION to setting `StreamResult.result_*`. This is REQUIRED
  because `ConversationRecorder` and phase metadata read `result.tokens.input_tokens /
  output_tokens` (the `AgentExecutionResult.tokens` accumulator), not only the
  `StreamResult`. Missing this would record a codex conversation as 0-token.
- Records to `ObservabilityCollector` as codex events arrive:
  - `item.started` with `item.type == command_execution` → `record_tool_started(tool_name="Bash", tool_use_id=<item id>, input_preview=<command>[:500])`,
  - `item.completed` command_execution → `record_tool_completed(tool_name="Bash", tool_use_id=<item id>, success=(exit_code==0), output_preview=<aggregated_output>[:500])`,
  - `item.completed` file_change → `record_tool_started/completed(tool_name="Edit", ...)` (single synthetic pair),
  - `turn.completed` → `record_token_usage(input=fresh_input, output=billable_output, cache_read=cached_input)` (per-turn delta; see token math),
  - end of stream → `record_session_summary(total_cost_usd=estimate, input_tokens=sum_input, output_tokens=sum_output, cache_read=sum_cache_read, cache_creation=0, num_turns=turns, duration_ms=<wall>, agent_id=None)`.

**Token math (double-count guard):** per `turn.completed`,
`fresh_input = max(0, usage.input_tokens - usage.cached_input_tokens)`,
`cache_read = usage.cached_input_tokens`,
`billable_output = usage.output_tokens + usage.reasoning_output_tokens`.
`record_token_usage` and `TokenAccumulator.record` are called ONCE per turn with these
per-turn deltas (the projection does `+=` and increments `turns`); the final
`record_session_summary` overwrites with the authoritative summed totals + estimated cost.
**A single-turn recording CANNOT validate per-turn vs cumulative usage** - the double-count
guard is only meaningful across turns. Therefore step 0 MUST capture a **multi-turn**
recording (a task that forces at least 2 turns). If the multi-turn capture shows `usage`
is cumulative (each `turn.completed` restates the running total), record the DELTA
(`this_turn − prior_cumulative`) instead of the raw per-turn value. Pin the observed
semantics with a test over the multi-turn recording.

**Exit + failure semantics (must-fix #6):** codex `--json` has no single `result.success`.
The authoritative phase result is `workspace.last_stream_exit_code` (the `codex exec`
process exit from the docker-exec stream), consumed by the handler (Task 5). Rules:
- Non-zero process exit ⇒ phase FAILS.
- Process exit 0 BUT the stream had malformed/unparseable JSON, OR ended with **no
  `turn.completed`** (no authoritative usage), OR the stream timed out ⇒ phase FAILS
  EXPLICITLY. `CodexStreamProcessor` sets `StreamResult.error_reason` and the handler maps
  a "successful process exit with no terminal usage" to a non-zero
  `AgentExecutionCompletedCommand.exit_code` (do NOT let absence-of-nonzero-exit become a
  silent success).
- A `command_execution` item with non-zero `exit_code` is a failed TOOL op only (recorded
  via `record_tool_completed(success=False)` + noted in `error_reason`); it does NOT by
  itself fail the phase, because codex may recover in a later turn.

**Steps (TDD):**

0. **Capture a real MULTI-TURN recording** (do NOT trust the schema blindly; single-turn
   cannot validate the double-count guard). On a machine with codex auth, in a throwaway
   git repo, force at least 2 turns (e.g. a task that requires an initial failed test run
   then a fix):
   ```bash
   codex exec --json --sandbox danger-full-access --skip-git-repo-check \
     "Create palindrome.py with is_palindrome(s). Write a pytest with a deliberately failing \
      case first, run it, observe the failure, then correct is_palindrome and re-run until green." \
     > codex_multiturn.jsonl 2>&1
   ```
   Copy `codex_multiturn.jsonl` into `.../execute_workflow/recordings/`. Inspect field
   names/nesting (`item.id` vs `item.item.id`; whether `usage` is under `turn.completed` or
   `turn.completed.usage`; whether per-turn usage is per-turn or cumulative across the
   turns) and adjust the parser accessors to match reality. Also hand-craft small fixtures:
   `codex_malformed.jsonl` (a truncated/garbage line), `codex_no_terminal.jsonl`
   (items but no `turn.completed`).
2. Failing test `test_codex_stream_processor.py`:
   ```python
   import json
   from pathlib import Path
   import pytest
   from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
       CodexStreamProcessor,
   )
   from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import TokenAccumulator

   class _RecordingCollector:
       def __init__(self): self.calls: list[tuple[str, dict]] = []
       async def record_tool_started(self, **k): self.calls.append(("tool_started", k))
       async def record_tool_completed(self, **k): self.calls.append(("tool_completed", k))
       async def record_token_usage(self, *a, **k): self.calls.append(("token_usage", {"args": a, **k}))
       async def record_session_summary(self, **k): self.calls.append(("summary", k))

   class _NoopWorkspace:
       last_stream_exit_code = 0
       async def interrupt(self) -> bool: return True

   async def _lines(path):
       for line in Path(path).read_text().splitlines():
           if line.strip():
               yield line

   @pytest.mark.asyncio
   async def test_codex_recording_produces_timeline():
       rec = Path(__file__).parent / "recordings" / "codex_multiturn.jsonl"
       collector = _RecordingCollector()
       tokens = TokenAccumulator()
       proc = CodexStreamProcessor(
           tokens=tokens, collector=collector, controller=None,
           execution_id="exec-1", phase_id="p1", session_id="s1", agent_model="gpt-5.1-codex",
       )
       result = await proc.process_stream(_lines(rec), _NoopWorkspace())
       kinds = [c[0] for c in collector.calls]
       assert "tool_started" in kinds and "tool_completed" in kinds
       assert "token_usage" in kinds
       summary = next(c[1] for c in collector.calls if c[0] == "summary")
       assert summary["input_tokens"] > 0 and summary["output_tokens"] > 0
       assert summary["total_cost_usd"] is not None and summary["total_cost_usd"] > 0
       assert result.num_turns >= 2                      # multi-turn recording
       assert result.result_cache_read >= 0              # cache_read separated from fresh input
       assert tokens.input_tokens == result.result_input_tokens   # shared accumulator updated
       assert result.conversation_lines                  # raw codex JSONL preserved

   @pytest.mark.asyncio
   async def test_malformed_json_fails_explicitly():
       rec = Path(__file__).parent / "recordings" / "codex_malformed.jsonl"
       proc = CodexStreamProcessor(tokens=TokenAccumulator(), collector=_RecordingCollector(),
           controller=None, execution_id="e", phase_id="p", session_id="s", agent_model="gpt-5.1-codex")
       result = await proc.process_stream(_lines(rec), _NoopWorkspace())
       assert result.error_reason is not None

   @pytest.mark.asyncio
   async def test_no_terminal_usage_fails_explicitly():
       rec = Path(__file__).parent / "recordings" / "codex_no_terminal.jsonl"
       proc = CodexStreamProcessor(tokens=TokenAccumulator(), collector=_RecordingCollector(),
           controller=None, execution_id="e", phase_id="p", session_id="s", agent_model="gpt-5.1-codex")
       result = await proc.process_stream(_lines(rec), _NoopWorkspace())
       assert result.error_reason is not None            # no turn.completed => not a silent success

   @pytest.mark.asyncio
   async def test_unknown_model_marks_cost_unavailable():
       rec = Path(__file__).parent / "recordings" / "codex_multiturn.jsonl"
       proc = CodexStreamProcessor(tokens=TokenAccumulator(), collector=_RecordingCollector(),
           controller=None, execution_id="e", phase_id="p", session_id="s", agent_model="mystery-model")
       result = await proc.process_stream(_lines(rec), _NoopWorkspace())
       assert result.total_cost_usd is None              # strict resolver => None, not Sonnet

   @pytest.mark.asyncio
   async def test_cancel_signal_interrupts(monkeypatch):
       # controller returns a CANCEL on the first poll; assert interrupt() called + interrupt_requested
       ...  # uses a fake controller + workspace.interrupt spy; asserts result.interrupt_requested is True
   ```
   Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/test_codex_stream_processor.py -q` → fails.
3. Implement `CodexStreamProcessor.process_stream`: iterate lines; `json.loads` each
   (the ONE `dict[str, Any]` JSON seam, mirroring `EventStreamProcessor`'s documented
   pattern); on a `JSONDecodeError` set `error_reason` and continue (or fail per the
   failure rules); poll cancel via reused `CancelSignalPoller.check(line_count)` and
   `await workspace.interrupt()` on interrupt (sets `interrupt_requested=True`); dispatch by
   top-level `type` (`thread.started`/`turn.started`/`item.started`/`item.completed`/
   `turn.completed`); accumulate into BOTH `self._tokens` and the running sums; on stream
   end, if `turn.completed` was never seen set `error_reason` (no authoritative usage);
   compute the estimate via the STRICT resolver:
   ```python
   pricing = resolve_model_pricing(self._agent_model)
   total_cost = (pricing.calculate_cost(sum_fresh_input, sum_output, cache_read=sum_cache_read)
                 if pricing is not None else None)   # None => cost unavailable, NOT Sonnet
   ```
   then emit `record_session_summary(total_cost_usd=total_cost, ...)`. Keep methods small
   (one per event type) for fitness-check.
4. Run → green.
5. `uv run pytest .../test_codex_stream_processor.py -q && just fitness-check`.
6. Lint/format; commit: `feat(codex): CodexStreamProcessor parses --json into the Lane-2 timeline`.

---

## Task 4 - `_build_codex_command` + command-builder dispatch

**Files:** `apps/syn-api/src/syn_api/_wiring.py`.

**Interfaces:**
- Produces `def _build_codex_command(phase: ExecutablePhase, prompt: str) -> list[str]`:
  ```python
  ["codex", "exec", "--json", "--sandbox", "danger-full-access",
   "--skip-git-repo-check", "--model", _resolve_codex_model(phase.agent_config.model), prompt]
  ```
  `danger-full-access` is MANDATORY (workspace-write silently no-ops writes under Docker,
  EXP-10/#258; the container is the security boundary). Prompt is the LAST single argv
  element (no `sh -c`).
  **Bind the actual model (must-fix #3):** pass `--model` with the resolved codex api name
  so codex does NOT run its container default while the dashboard labels/prices it as
  `gpt-5.1-codex`. `_resolve_codex_model(model)` maps the phase model
  (`"codex"`/`"gpt-codex"`/`"gpt-5.1-codex"`) to codex's `--model` value (api name
  `gpt-5.1-codex`). As a belt-and-suspenders check, `CodexStreamProcessor` should read the
  model reported in the codex `thread.started`/config event if present and prefer THAT for
  telemetry/pricing when it disagrees with the requested model (log a warning on mismatch),
  so cost is never labeled for a model codex did not actually run.
- Produces `def _build_agent_command(phase: ExecutablePhase, prompt: str) -> list[str]`
  that dispatches: `return _build_codex_command(phase, prompt) if phase.agent_config.provider == "codex" else _build_claude_command(phase, prompt)`.
- Change `get_execution_processor()` to pass `command_builder=_build_agent_command`
  (was `_build_claude_command`). The `CommandBuilder` type
  (`Callable[[ExecutablePhase, str], list[str]]`) is unchanged.

**Steps (TDD):**
1. Failing test (co-located `apps/syn-api/.../test_wiring_command_builder.py`, or extend an
   existing wiring test):
   ```python
   from syn_api._wiring import _build_agent_command, _build_codex_command, _build_claude_command
   from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
       AgentConfiguration, ExecutablePhase,
   )

   def _phase(provider):
       return ExecutablePhase(phase_id="p", name="n", order=1,
                              agent_config=AgentConfiguration(provider=provider, model="codex"))

   def test_codex_command_shape():
       cmd = _build_codex_command(_phase("codex"), "do the thing")
       assert cmd == ["codex","exec","--json","--sandbox","danger-full-access",
                      "--skip-git-repo-check","--model","gpt-5.1-codex","do the thing"]

   def test_dispatch_routes_by_provider():
       assert _build_agent_command(_phase("codex"), "x")[0] == "codex"
       assert _build_agent_command(_phase("claude"), "x")[0] == "claude"
       # claude path unchanged
       assert _build_agent_command(_phase("claude"), "x") == _build_claude_command(_phase("claude"), "x")
   ```
   Run: `uv run pytest apps/syn-api -k command_builder -q` → fails.
2. Implement the two functions + wiring swap.
3. Run → green.
4. `just docs-sync` (no OpenAPI change expected, but proves no drift). Lint/format.
5. Commit: `feat(codex): _build_codex_command + provider-dispatched command builder`.

---

## Task 5 - Parser selection in AgentExecutionHandler (`runner` param)

**Files:** `handlers/AgentExecutionHandler.py`, `processor_types.py` (Protocol),
`WorkflowExecutionProcessor.py`.

**Interfaces:**
- New `Runner = Literal["claude", "codex"]` in `processor_types.py`.
  `AgentHandlerProtocol.handle(...)` and `AgentExecutionHandler.handle(...)` gain
  `runner: Runner = "claude"` (typed Literal, NOT `str`; defaulted so every existing
  caller/test double stays valid; pyright flags drift because the Protocol changed in
  lockstep and rejects any non-`{claude,codex}` value).
- In `AgentExecutionHandler.handle`, the non-interactive branch selects the parser:
  ```python
  if runner == "codex":
      processor = CodexStreamProcessor(
          tokens=tokens, collector=collector, controller=self._controller,
          execution_id=todo.execution_id, phase_id=todo.phase_id,
          session_id=session_id, agent_model=agent_model,
      )
  else:
      processor = EventStreamProcessor(...)  # unchanged
  stream_result = await processor.process_stream(
      workspace.stream(claude_cmd, timeout_seconds=timeout_seconds, environment=agent_env),
      workspace,
  )
  ```
  The `interactive_prompt is not None` branch is untouched. `record_session_summary` is
  emitted from EXACTLY ONE layer: claude via the handler (today), codex via
  `CodexStreamProcessor` - so the handler guards its own call with `if runner != "codex"`
  (the double-emission guard the reviewer confirmed correct).
- **Authoritative exit (must-fix #6):** for codex, exit-code detection uses
  `workspace.last_stream_exit_code` as authoritative (non-zero ⇒ fail). Additionally, if
  the process exited 0 but `stream_result.error_reason is not None` (malformed JSON, no
  `turn.completed`, timeout), the handler builds `AgentExecutionCompletedCommand` with a
  non-zero `exit_code` (e.g. `1`) so the phase fails explicitly rather than passing on the
  absence of a nonzero exit. For claude, `_detect_exit_code` is unchanged. Token totals in
  `AgentExecutionCompletedCommand` come from `stream_result.result_*` (with
  `result.tokens` fallback) exactly as today.
- `WorkflowExecutionProcessor._handle_run_agent` computes and passes a typed runner
  derived STRICTLY from provider (no `agent_id` fallback):
  ```python
  runner: Runner = "codex" if phase.agent_config.provider == "codex" else "claude"
  result = await self._get_agent_handler().handle(..., agent_id=phase.agent_config.agent_id, runner=runner)
  ```

**Steps (TDD):**
1. Failing test in `test_handlers.py`: drive `AgentExecutionHandler.handle(runner="codex", ...)`
   with a fake workspace whose `stream()` yields lines from the codex recording and
   `last_stream_exit_code = 0`; assert the returned `AgentExecutionResult.command` has
   `exit_code == 0` and non-zero `input_tokens/output_tokens`, and that the handler did NOT
   itself call `collector.record_session_summary` (codex path emits it internally). A
   parallel `runner="claude"` case asserts unchanged behavior against a stream-json fixture.
   Run: `uv run pytest .../handlers/test_handlers.py -q` → fails.
2. Implement the `runner` param + branch + double-emit guard + Protocol update + processor
   derivation.
3. Run → green. Run the full execute_workflow suite to prove claude untouched:
   `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow -q`.
4. `just fitness-check` (AgentExecutionHandler is large; ensure the branch stays under
   gates by extracting a 3-line `_make_stream_processor(runner, ...)` helper if needed).
5. Commit: `feat(codex): select CodexStreamProcessor by runner in AgentExecutionHandler`.

---

## Task 6 - Provider selection through YAML -> domain + contradiction validation

**Files:** `_shared/workflow_definition.py`, `aggregate_workflow_template/value_objects.py`
(docstring only), `aggregate_execution/value_objects.py` (agent_id default),
`_shared/ExecutionValueObjects.py` (agent_id default - the SECOND mirror), plus tests in
the workflow_definition and value-object test modules.

**Interfaces:**
- `AgentYamlDefinition.provider: Literal["claude","claude-interactive","codex"] | None`.
- `AgentYamlDefinition` gets a `@model_validator(mode="after")`:
  ```python
  @model_validator(mode="after")
  def _validate_provider_agent_combo(self) -> "AgentYamlDefinition":
      if self.provider == "codex" and self.agent_id not in (None, "codex"):
          raise ValueError(
              "agent.provider='codex' selects the programmatic codex harness; "
              "agent_id must be omitted or 'codex' (it does not select a tmux pane here)."
          )
      return self
  ```
- `PhaseDefinition.provider` stays `str | None` (no structural change); update its docstring
  to list `codex`. `AgentConfiguration.provider` stays `str` (no change). The docker path
  selectors (`_workspace_service_for`, `_is_interactive_phase`) require NO change - verified
  they treat any non-`claude-interactive` provider as the docker path.
- **`AgentConfiguration.agent_id` invariant (must-fix #8), BOTH mirrors:** change
  `agent_id: str = "claude"` to `agent_id: str | None = None` in
  `aggregate_execution/value_objects.py` (line 77) AND `_shared/ExecutionValueObjects.py`
  (line ~52). Update `_build_agent_config_from_phase` (ExecuteWorkflowHandler line 149) to
  pass `agent_id=phase_agent_id` (already `None` when YAML omits it - drop the
  `or defaults.agent_id` coercion so codex phases no longer silently read `"claude"`).
  Update `_provisioned_agents` (WorkspaceProvisionHandler line 108) to coerce
  `agent_id or "claude"` at the interactive-tmux boundary only, preserving PR #765
  behavior. `runner` dispatch is unaffected (it reads `provider`, not `agent_id`).
- `WorkspaceProvisionHandler._build_provision_result`: guard the claude plugin-dir append so
  codex argv is never polluted:
  ```python
  if not is_interactive and phase.agent_config.provider != "codex":
      _append_claude_plugin_dirs(claude_cmd, phase)
  ```
  (Codex demo phases carry no `claude_plugins`; this guard is defense-in-depth.)

**Steps (TDD):**
1. Failing tests in `test_workflow_definition.py` + a value-object test:
   - `agent: {provider: codex}` parses and `to_domain().provider == "codex"`,
     `to_domain().agent_id is None`.
   - `agent: {provider: codex, agent_id: gemini}` raises `ValidationError`.
   - `agent: {provider: claude-interactive, agent_id: codex}` STILL parses (unchanged).
   - `AgentConfiguration()` default `agent_id is None` in BOTH mirrors; a codex
     `AgentConfiguration(provider="codex")` has `agent_id is None` (not `"claude"`).
   - `_provisioned_agents` for an interactive phase with `agent_id=None` returns
     `("claude",)` (boundary coercion preserved).
   Run: `uv run pytest packages/syn-domain -k "workflow_definition or agent_config" -q` → fails.
2. Implement Literal + validator + provision guard + both-mirror agent_id default +
   `_build_agent_config_from_phase`/`_provisioned_agents` updates.
3. Run → green; run the interactive-tmux template + PR-#765 multi-agent tests to prove no
   regression.
4. Commit: `feat(codex): route provider='codex' phases through the docker codex harness`.

---

## Task 7 - Codex auth injection via ADR-024 setup phase (0600, file-only)

**Files:** `setup_phase_secrets.py`, `settings/config.py`, `settings/constants.py`,
`env_constants.py`, `scripts/op_env_export.py`, `test_setup_phase_secrets.py`.

**Canonical name (used identically everywhere):** `CODEX_AUTH_JSON`.
- `packages/syn-shared/src/syn_shared/settings/constants.py`:
  `ENV_CODEX_AUTH_JSON = "CODEX_AUTH_JSON"`.
- `env_constants.py`: re-export `ENV_CODEX_AUTH_JSON`.
- `settings/config.py` `Settings` (bare env, no prefix - matches `anthropic_api_key`):
  `codex_auth_json: SecretStr | None = Field(default=None, description="Full contents of codex ~/.codex/auth.json (ChatGPT-subscription auth). Injected file-only during setup phase; never argv/logs.")`.
- `scripts/op_env_export.py`: import `ENV_CODEX_AUTH_JSON` and add to `_KEYS`; 1Password
  field label = `CODEX_AUTH_JSON`.

**Interfaces:**
- `SetupPhaseSecrets` gains `codex_auth_json: str | None = None`.
- `_resolve_codex_credentials() -> str | None` reads
  `get_settings().codex_auth_json.get_secret_value()` (mirrors `_resolve_claude_credentials`).
  Called inside `SetupPhaseSecrets.create(...)` and populated on the returned instance.
  `for_testing(...)` gains `codex_auth_json: str | None = None` (reads `CODEX_AUTH_JSON`
  from env as fallback).

- **RESTRUCTURE `build_setup_script()` (must-fix #1 - DEMO-BREAKING today):** the method
  currently returns `DEFAULT_SETUP_SCRIPT` EARLY when `not self.repositories`. The demo is
  `requires_repos: false`, so with the naive "append after the repos block" approach the
  codex auth is NEVER written and codex starts UNAUTHENTICATED. Restructure so credential
  material is ALWAYS emitted regardless of repository presence:
  ```python
  def build_setup_script(self) -> str:
      lines = [DEFAULT_SETUP_SCRIPT.rstrip()]
      self._append_codex_auth(lines)      # ALWAYS (independent of repos)
      if self.repositories:
          self._append_git_credentials(lines)   # existing repo block, extracted
          self._append_repo_clones(lines)
      return "\n".join(lines) + "\n"
  ```
  `_append_codex_auth(lines)` runs unconditionally so the repo-less demo path still writes
  auth. (Extract the existing per-repo credentials + clone logic into the two helpers to
  keep `build_setup_script` under the fitness-check complexity gate.)

- `_append_codex_auth(lines)`, when `self.codex_auth_json`:
  ```
  # Configure codex auth (file-only). ~/.codex created at RUNTIME (/home/agent is tmpfs).
  mkdir -p -m 700 ~/.codex
  cat > ~/.codex/auth.json << 'CODEXAUTHEOF'
  <codex_auth_json>
  CODEXAUTHEOF
  chmod 600 ~/.codex/auth.json
  ```
  - `mkdir -p -m 700 ~/.codex` (dir 700) and `chmod 600 ~/.codex/auth.json` (must-fix #2).
  - **Heredoc-delimiter safety (must-fix #2):** if the auth content contains a line equal
    to the delimiter it would terminate the heredoc early / corrupt or partially leak. Two
    options: (a) validate/reject auth content containing `CODEXAUTHEOF` and raise a clear
    error at `SetupPhaseSecrets` build time; or (b) PREFER a safer materialization that
    avoids heredoc entirely - write the auth via `workspace.inject_files([(".codex/auth.json",
    content.encode())], base_path="/home/agent")` (the same copy-to mechanism claude
    plugins use) and only `chmod`/`mkdir` in the script. Option (b) is recommended: no
    delimiter risk, secret never in the script text at all. If (b) is used, `~/.codex`
    perms are set by a tiny script line, and the setup-script no longer carries the secret.
  - Do NOT add `CODEX_AUTH_JSON` to `_build_setup_env` - file-only injection, no env var, so
    it never lands in the container environment or leaks via `env`.

- **Cleanup-on-failure (must-fix #2):** in `setup_phase.run_setup_phase`, the setup script
  (with option (a)) contains the credential and today a non-zero setup exit RETURNS before
  `clear_secrets()`, leaving `/workspace/.setup/setup.sh` with the secret. Wrap the run so
  `clear_secrets(ws)` runs in a `finally`:
  ```python
  try:
      result = await ws.execute(["bash","/workspace/.setup/setup.sh"], environment=setup_env, ...)
      if result.exit_code != 0:
          logger.error("Setup phase failed (exit=%d): %s", result.exit_code, result.stderr)
      return result
  finally:
      await clear_secrets(ws)   # removes /workspace/.setup, shell history, /tmp/setup*
  ```
  **`auth.json` MUST REMAIN** - codex needs it for the agent phase. `clear_secrets` only
  removes transient setup material (`/workspace/.setup`, history, `/tmp/setup*`) and already
  keeps `~/.git-credentials`; `~/.codex/auth.json` lives under `/home/agent` and is
  untouched by `clear_secrets`. Verify `clear_secrets` never rm's `~/.codex`.

**Steps (TDD):**
1. Failing tests in `test_setup_phase_secrets.py`:
   ```python
   def test_codex_auth_written_even_without_repos():
       # DEMO-BREAKING regression guard: repo-less path MUST still write codex auth
       s = SetupPhaseSecrets.for_testing(codex_auth_json='{"tokens":{"access_token":"x"}}')
       assert s.repositories == []
       script = s.build_setup_script()
       assert "mkdir -p -m 700 ~/.codex" in script
       assert "chmod 600 ~/.codex/auth.json" in script

   def test_codex_auth_dir_and_file_perms():
       s = SetupPhaseSecrets.for_testing(codex_auth_json='{"a":1}', repositories=["https://github.com/o/r"])
       script = s.build_setup_script()
       assert "mkdir -p -m 700 ~/.codex" in script
       assert "chmod 600 ~/.codex/auth.json" in script

   def test_codex_auth_heredoc_delimiter_rejected_or_avoided():
       # option (a): reject; option (b): inject_files (no delimiter in script at all)
       import pytest
       bad = "line1\nCODEXAUTHEOF\nline2"
       with pytest.raises(ValueError):
           SetupPhaseSecrets.for_testing(codex_auth_json=bad).build_setup_script()

   def test_codex_auth_not_in_setup_env():
       from syn_adapters.workspace_backends.service.setup_phase import _build_setup_env
       s = SetupPhaseSecrets.for_testing(codex_auth_json='{"a":1}')
       assert "CODEX_AUTH_JSON" not in _build_setup_env(s)
   ```
   Plus a `setup_phase` test asserting `clear_secrets` runs even when the setup script exits
   non-zero (spy the workspace `execute` calls; assert the cleanup script ran in `finally`),
   and that `~/.codex/auth.json` is NOT among the paths `clear_secrets` removes.
   Run: `uv run pytest packages/syn-adapters -k "setup_phase" -q` → fails.
2. Implement field + resolver + restructured script (always-write auth) + finally-cleanup +
   settings/constants/env_constants/op wiring.
3. Run → green.
4. `just docs-sync` (regenerates `.env.example` from Pydantic Settings - proves the new
   field surfaces). Confirm `CODEX_AUTH_JSON` appears in `.env.example`.
5. Grep guard: `grep -rn "codex_auth_json\|CODEX_AUTH_JSON" --include=*.py .` shows no
   argv/log usage. Commit: `feat(codex): inject ~/.codex/auth.json via ADR-024 setup phase (0600, file-only)`.

---

## Task 8 - Codex CLI in the default workspace image (SUBMODULE)

**Files:** `lib/agentic-primitives/providers/workspaces/claude-cli/Dockerfile`.

**Why:** the default `claude-cli` image (what the docker `WorkspaceService` provisions)
does not install codex; only `interactive-tmux` does. The bridge runs codex in the default
docker workspace, so codex must be present there.

**Interfaces (Dockerfile):** mirror the interactive-tmux install, pinned EXACTLY:
```dockerfile
ARG CODEX_CLI_VERSION=0.139.0
RUN npm install -g @openai/codex@${CODEX_CLI_VERSION} && codex --version
LABEL agentic.codex_cli_version=${CODEX_CLI_VERSION}
```
Codex installs globally to `/usr/local` (survives the `/home/agent` tmpfs mount);
`~/.codex` is created at RUNTIME by the setup script (Task 7), never baked in.

**Steps (must-fix #5 - use the STAGED build, not raw `docker build`):**
1. Add the ARG/RUN/LABEL near the existing `claude-code` install (Dockerfile line ~98).
2. **Build via the staged builder** (the claude-cli Dockerfile needs staged wheels/plugins;
   a raw `docker build` from the provider dir will fail). Build locally before pushing any
   tag (feedback_local_build_before_base_bump):
   ```bash
   cd lib/agentic-primitives
   uv run scripts/build-provider.py claude-cli --tag codex-bridge
   docker run --rm <built-image>:codex-bridge codex --version
   docker run --rm <built-image>:codex-bridge claude --version
   ```
3. Push to GHCR under a bridge tag; point the dev stack at it via
   `SYN_WORKSPACE_DOCKER_IMAGE` (or the `WorkspaceServiceConfig.image` default). Commit in
   the submodule; bump the pointer in syn137.
4. Commit (submodule): `feat(workspace): install @openai/codex@0.139.0 in claude-cli image`.

**Networking (egress fear DEBUNKED - smoke-test only, no change needed):**
`agent-net` is **NOT `internal: true`** (`docker/docker-compose.yaml` line 244-245: "agents
need egress for git operations"), agent containers get **no forced `HTTP(S)_PROXY`**, and
`SecurityPolicy.allowed_hosts` is **not network-enforced by the docker provider**. So
`codex exec` reaches `api.openai.com` DIRECTLY today with no networking change. The only
demo step is a smoke-test verification:
`docker exec <ws> curl -sS -o /dev/null -w '%{http_code}\n' https://api.openai.com/v1/models`
(expect 401/200, not a timeout). **Do NOT** describe the topology as Envoy-only/allowlisted.
Future-hardening note: if egress is later locked down (`internal: true`), adding
`api.openai.com` to an `allowed_hosts` tuple does NOTHING (it is not network-enforced) - the
real fix would require an Envoy OpenAI vhost + TLS cluster + token-injector passthrough +
pointing codex at that base URL/proxy. Out of scope for the demo.

---

## Task 9 - Demo workflow + e2e + mixed-workflow back-compat

**Files:** `workflows/demo/codex-bridge-demo.yaml` (N), `test_codex_bridge_e2e.py` (N).

**Demo workflow (single codex phase):**
```yaml
name: codex-bridge-demo
description: One codex phase, live dashboard timeline
requires_repos: false
phases:
  - id: codex-implement
    name: Codex implements a small feature
    order: 1
    agent:
      provider: codex
      model: gpt-5.1-codex
    timeout_seconds: 600
    prompt_template: |
      Create palindrome.py with is_palindrome(s: str) -> bool and a pytest with
      three cases. Run the tests and report the result.
    output_artifacts: [text]
```

**Interfaces / tests:**
- `test_codex_bridge_e2e.py` (in-process, fake workspace whose `stream()` replays the
  Task-3 recording): run `WorkflowExecutionProcessor.run(...)` with one `provider="codex"`
  phase; assert the execution completes, a `session_summary` observation was recorded with
  `total_cost_usd > 0` and codex model, and tool-op observations exist (the timeline).
- **Mixed-workflow back-compat:** a two-phase workflow `[claude phase, codex phase]` on the
  SAME docker service; assert claude phase produces stream-json-derived tokens and codex
  phase produces `--json`-derived tokens, both flowing to the same projection; assert
  `agent_id`/interactive paths are never engaged.
- A pure-claude workflow regression asserting IDENTICAL built command + recorded events
  (run the existing `test_execute_workflow.py` + `test_recording_replay.py` suites
  unchanged; add an assertion that `_build_agent_command` for a claude phase equals
  `_build_claude_command` exactly).

**Artifact collection for the demo (secondary #c):** the demo has one codex phase writing
files. Confirm the `COLLECT_ARTIFACTS` step tolerates an EMPTY collection (codex may write
into `/workspace/repos/...` or leave no `artifacts/output/*`), OR require a sentinel output
artifact so `_handle_complete_phase` does not surface a spurious `no_artifacts` failure. The
processor already treats `no_artifacts` as a non-fatal WARNING
(`WorkflowExecutionProcessor._handle_complete_phase` appends `"no_artifacts"` to `warnings`,
not an error), so an empty collection completes the phase - but the demo prompt should ask
codex to write to `/workspace/artifacts/output/result.txt` so the timeline shows a real
artifact. Add an e2e assertion for whichever choice is made.

**Steps (TDD):**
1. Write the e2e + mixed tests → fail.
2. Wire the demo YAML into the test fixtures; implement any missing glue.
3. Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow -q`.
4. `just qa` (or at minimum `just fitness-check && just docs-sync && uv run ruff check . && uv run ruff format --check .`).
5. Commit: `test(codex): e2e demo + mixed-workflow back-compat`.

---

## Task 10 - stdin DEVNULL on the non-interactive stream path (must-fix #7)

**Files:** `packages/syn-adapters/.../workspace_backends/agentic/stream_adapter.py`,
`.../agentic/test_stream_adapter.py`.

**Why:** the stream path runs `docker exec -i ... <argv>` via
`create_subprocess_exec(*exec_cmd, stdout=PIPE, stderr=STDOUT)` with **stdin inherited**
from syn-api. Under `-i`, a codex process that touches stdin can block forever.

**Interface:** add `stdin=asyncio.subprocess.DEVNULL` to the `create_subprocess_exec` call
in `AgenticStreamAdapter.stream` (the single non-interactive stream path). `claude -p` does
not read stdin, so this is safe for claude too; keep `-i` (harmless with DEVNULL) to
minimize the diff, OR drop `-i` for this path - pick DEVNULL as the smaller, safer change.

**Steps (TDD):**
1. Failing test: a subprocess that reads stdin (`cat`) must terminate promptly rather than
   hang when driven through the adapter with DEVNULL. Assert the stream completes and the
   claude stream-json fixture still parses unchanged (regression).
   Run: `uv run pytest packages/syn-adapters -k stream_adapter -q` → fails/hangs before fix.
2. Add `stdin=asyncio.subprocess.DEVNULL`.
3. Run → green; run the full workspace-backend suite to prove claude streaming unaffected.
4. Commit: `fix(workspace): close stdin (DEVNULL) on non-interactive stream so codex cannot hang`.

---

## Task 11 - Codex-aware interruption (must-fix #4)

**Files:** `.../service/managed_workspace_ops.py`, `.../service/managed_workspace.py`,
`.../service/test_interrupt.py` (N).

**Why:** `interrupt_container` runs `pgrep -n claude` - it will NOT stop `codex exec`, so a
codex phase is uncancellable today. `CodexStreamProcessor` polls the cancel signal and calls
`workspace.interrupt()`, which must actually terminate codex.

**Interface options (pick the most reliable):**
- Make `interrupt_container` / `_send_sigint` process-name aware: accept the active agent
  process name (`"claude"` or `"codex"`) and `pgrep -n <name>`; `ManagedWorkspace.interrupt`
  is called from the stream processor which knows the runner, so thread `runner`/process
  name through. Simple, targeted.
- OR (more robust) signal ALL known agent processes:
  `sh -c "pkill -INT -f 'codex|claude' || kill -INT $(pgrep -n node) || true"`, or kill the
  active `docker exec` / terminate the container. Terminating the container is the surest
  unblock (mirrors the interactive path's `driver.stop()` teardown) but is heavier.

Recommended for the demo: thread the process name so `interrupt(process="codex")` runs
`pgrep -n codex`; fall back to container SIGTERM if `pgrep` finds nothing. `interrupt` must
return a bool as today (non-fatal on failure).

**Steps (TDD):**
1. Failing test: a fake `docker exec` recorder asserts that interrupting a codex workspace
   issues a `pgrep -n codex`-based kill (not `pgrep -n claude`), and that the claude path is
   unchanged (`pgrep -n claude`).
   Run: `uv run pytest packages/syn-adapters -k interrupt -q` → fails.
2. Implement process-aware interrupt + thread the runner/process name from
   `AgentExecutionHandler`/`CodexStreamProcessor` into `workspace.interrupt`.
3. Run → green; add a `CodexStreamProcessor` cancel test asserting `interrupt` is invoked
   and `StreamResult.interrupt_requested is True` on a CANCEL signal.
4. Commit: `fix(workspace): make interrupt() codex-aware so codex phases are cancellable`.

---

## Effort estimate (agent-days)

| Task | Scope | Estimate |
|---|---|---|
| 1 Codex pricing + strict resolver | pure, unit | 0.25 |
| 2 Cost model-resolution bug fix | 2 one-liners + tests | 0.25 |
| 3 CodexStreamProcessor + recording | core parser, needs real capture | 1.0 |
| 4 `_build_codex_command` + dispatch | small | 0.25 |
| 5 Parser selection (runner) | handler + Protocol + processor | 0.5 |
| 6 Provider YAML + validation | Literal + validator + guard | 0.5 |
| 7 Codex auth injection | secrets + settings + op | 0.5 |
| 8 Codex in staged image (submodule) + egress smoke | staged build/push + smoke | 0.75 |
| 9 Demo YAML + e2e + back-compat | tests + glue | 0.75 |
| 10 stdin DEVNULL | 1 line + regression | 0.25 |
| 11 Codex-aware interrupt | process-aware + tests | 0.5 |
| Buffer (integration, live smoke on dev stack, review pass) | | 1.0 |
| **Total** | | **~6.5 agent-days** |

## Critical path to the demo

The schedule uncertainty is NOT parser implementation (the recording-playback makes it
deterministic) - it is **day-1 image publication + a real-auth + egress smoke run**. Both
must land on day 1 because they gate every live iteration:
1. Publish the codex-enabled staged image (Task 8) and point the dev stack at it.
2. Capture the multi-turn codex recording (Task 3 step 0) - blocks the parser.
3. Smoke-test real codex auth + `api.openai.com` egress from a live workspace container.

Functional critical path:

**Task 3 (parser, needs the multi-turn capture) → Task 4 (command, `--model`) → Task 5
(runner selection + authoritative exit) → Task 7 (repo-less auth + finally-cleanup) →
Task 8 (staged image, in parallel) → Task 11 (codex-aware cancel) → Task 9 (live e2e).**

Tasks 1, 2, 6, 10 are parallelizable and off the critical path. Minimum viable live demo =
Tasks 3+4+5+7+8+10 wired on the dev stack (Task 11 needed only if the demo shows
cancellation).

## Demo runbook (exact commands)

```bash
# 0. One-time: store codex auth.json contents as a secret (1Password field CODEX_AUTH_JSON
#    for the dev vault, or export locally for a dev-stack run)
export CODEX_AUTH_JSON="$(cat ~/.codex/auth.json)"

# 1. Point the workspace image at the codex-enabled build
export SYN_WORKSPACE_DOCKER_IMAGE="ghcr.io/agentparadise/agentic-workspace-claude-cli:codex-bridge"

# 2. Bring the dev stack up (API on 8137)
just dev-down && just dev

# 3. Verify OpenAI egress from a throwaway workspace container (top risk gate)
#    (spin a workspace via the API or docker run the image, then:)
#    docker exec <ws> curl -sS -o /dev/null -w '%{http_code}\n' https://api.openai.com/v1/models   # expect 401/200, not a timeout

# 4. Register + run the demo workflow via the CLI
syn workflow create --file workflows/demo/codex-bridge-demo.yaml
syn workflow run codex-bridge-demo

# 5. Watch the live timeline in the dashboard (tokens/cost/tool-ops for the codex phase)
open http://localhost:8137   # or the dashboard-ui dev URL

# 6. Confirm cost is codex-priced + labeled estimated (not sonnet)
syn execution show <execution-id>   # cost_display should reflect gpt-5.1-codex, marked estimated
```

## Test strategy

- **Unit:** pricing (codex entries, strict resolver returns None on unknown, explicit
  cached-input multiplier, no-double-count math); cost model-resolution (both read paths);
  `_build_codex_command` argv shape incl. `--model`; provider/agent_id contradiction
  validator + both-mirror `agent_id` default; codex auth script (dir 700 / file 0600,
  heredoc-delimiter rejected-or-avoided, ALWAYS written even repo-less, not in setup env);
  finally-cleanup on setup failure; stdin DEVNULL; codex-aware interrupt.
- **Recording-playback (the reliability backbone):** capture a real **multi-turn**
  `codex exec --json` run (single-turn cannot validate per-turn vs cumulative usage), commit
  it under `recordings/` alongside hand-crafted `codex_malformed.jsonl` /
  `codex_no_terminal.jsonl`. Drive `CodexStreamProcessor` and
  `AgentExecutionHandler(runner="codex")` against them. Assert: field names/nesting and token
  math match reality; malformed JSON / missing `turn.completed` / timeout FAIL explicitly;
  cancellation sets `interrupt_requested`; unknown model marks cost unavailable (None);
  the shared `TokenAccumulator` is updated; raw codex JSONL survives in `conversation_lines`.
- **e2e (in-process):** `WorkflowExecutionProcessor.run` with a fake workspace replaying the
  recording; assert the full To-Do chain (PROVISION → RUN_AGENT → COLLECT → COMPLETE) runs
  (COLLECT tolerates empty/sentinel artifacts) and a codex `session_summary` + tool
  observations reach the projection.
- **Mixed-workflow back-compat:** `[claude, codex]` phases on the same service; both produce
  correct per-model tokens/cost; interactive paths never engaged. Plus the untouched claude
  suites (`test_execute_workflow.py`, `test_recording_replay.py`, session_cost) run green,
  and an assertion that the claude built command + recorded events are IDENTICAL to today
  (behavioral parity, not a no-edit claim).
- **Live smoke (dev stack):** the runbook above, once against a real codex auth + image +
  `api.openai.com` egress check.

## Why the bridge dodges the AP-path must-fixes

The prior codex review of the AP `run_agent`/RunExecutor path raised several must-fixes;
the bridge sidesteps most because it reuses proven machinery instead of a new executor:

- **Processor-chain rewrite:** the AP path had to re-thread the To-Do chain. The bridge
  reuses `WorkflowExecutionProcessor` unchanged - codex rides the existing PROVISION →
  RUN_AGENT → COLLECT → COMPLETE chain via `workspace.stream(codex_argv)`.
- **New observability plumbing:** the AP path needed a fresh telemetry sink. The bridge
  feeds the SAME `ObservabilityCollector` and `SessionCostProjection`, so the dashboard
  timeline already exists.
- **Exit handling:** codex has no `result.success`; the authoritative result is
  `workspace.last_stream_exit_code` → `AgentExecutionCompletedCommand.exit_code`, and
  malformed JSON / missing `turn.completed` / timeout are mapped to explicit failure so a
  run cannot masquerade as success on the mere absence of a nonzero exit (Task 5/6).
- **Secret handling:** reuses ADR-024 setup-phase injection (file-only, dir 700 / file
  0600, transient script cleaned in `finally`) rather than inventing credential flow;
  canonical `CODEX_AUTH_JSON` name across resolver + Pydantic + generated env + 1Password.

The bridge still owns the codex-specific traps the AP review flagged, addressed here
explicitly: (1) cost double-count / unknown-model→sonnet default (Tasks 1+2+3: fresh-input
vs cache_read separation, STRICT `resolve_model_pricing` in the codex path, model threaded
on both read paths, authoritative estimate emitted in `session_summary`, cached-input
multiplier made explicit + tested); (2) repo-less credential materialization (Task 7 -
codex auth written independent of repository presence, the top DEMO-BREAKING fix); and
(3) conversation/session_log storage - codex raw JSONL is stored provider-native in
`StreamResult.conversation_lines` (the existing `ConversationRecorder` path) and the shared
`TokenAccumulator` is updated so conversation metadata is not 0-token; downstream
conversation readers must tolerate provider-native (non-claude-shaped) lines. Auth is
file-only, never in argv/logs/events/commits.
