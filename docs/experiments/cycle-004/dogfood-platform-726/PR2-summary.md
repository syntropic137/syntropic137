# PR2 ready for commit

> **PARTIALLY SUPERSEDED 2026-05-05** — the materialization wiring described here (WorkspaceProvisionHandler hook, ResolvedClaudePlugin on ExecutablePhase, --plugin-dir flag emission, MaterializerService) is unchanged and shipped as-is. What changed: the upstream plugin registration that fills the lock projection now happens in the CLI tier, not the API container, per ADR-066. See `redesign-thin-api.md` for the corrected design. PR2's downstream wiring works against either upstream design.

Issue: [#726](https://github.com/syntropic137/syntropic137/issues/726) - workflow-scoped claude-plugin injection (the materialization switch).

## What this PR does

PR1 shipped the dormant plumbing (storage, fetcher, aggregates, lock projection, API routes, CLI). PR2 flips the switch: any workflow YAML that declares `claude_plugins:` now materializes the resolved plugin trees inside the agent workspace at provision time and emits matching `--plugin-dir` flags on the claude CLI invocation. Behavior is unchanged for workflows without `claude_plugins:`.

## Files modified

- `apps/syn-api/src/syn_api/_wiring.py` (+ materializer singleton, processor + dispatcher injection)
- `apps/syn-api/src/syn_api/services/claude_plugin_resolution_service.py` (+ `resolve_for_phase`)
- `packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/yaml_to_command.py` (carry `claude_plugins`)
- `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_workflow_template/WorkflowTemplateAggregate.py` (workflow-scope state + replay)
- `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/commands/CreateWorkflowTemplateCommand.py` (new field)
- `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/WorkflowTemplateCreatedEvent.py` (new field)
- `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/ExecuteWorkflowHandler.py` (resolver injection, async `_get_executable_phases`, populates `ExecutablePhase.claude_plugins`)
- `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py` (materializer pass-through to `WorkspaceProvisionHandler`)
- `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/WorkspaceProvisionHandler.py` (`_materialize_claude_plugins` + `--plugin-dir` flag emission)

## Files created

- `apps/syn-api/src/syn_api/services/claude_plugin_materializer.py`
- `apps/syn-api/tests/test_claude_plugin_materializer.py` (5 cases)
- `docs/experiments/cycle-004/dogfood-platform-726/e2e-smoke-pr2.sh`
- `docs/experiments/cycle-004/dogfood-platform-726/PR2-summary.md` (this file)

## Tests added (this PR)

- `apps/syn-api/tests/test_claude_plugin_materializer.py`: 5 cases (empty, prefix, multi-plugin, LRU hit, LRU eviction).
- `apps/syn-api/tests/test_claude_plugin_resolution_service.py`: 6 new cases covering `resolve_for_phase` (empty, global-only, workflow-overrides-global, phase-overrides-workflow, deterministic order, missing-lock raises).
- `packages/syn-domain/.../handlers/test_handlers.py`: 2 new cases on `WorkspaceProvisionHandler` (materialize + flag emission, skip when no plugins).

Total PR2 tests: **13 new cases**.

## QA

- `uv run ruff check` clean on all PR2 files.
- `uv run ruff format --check` clean on all PR2 files.
- `uv run pyright` clean on all PR2 files (0 errors; the only warning is the pre-existing `syn_domain.contexts.artifacts.domain.ports.artifact_storage` import resolution noise that already exists on `main`).
- `uv run pytest packages/syn-domain/ apps/syn-api/tests/ --deselect apps/syn-api/tests/test_webhooks_handlers.py`: **1541 passed**, 83 deselected. The lone `test_webhooks_handlers` failure is pre-existing on `main` (verified via `git stash`); unrelated to PR2.

## Stop-and-reassess findings

1. **`WorkflowTemplateAggregate` did not carry workflow-scope `claude_plugins`.** Per-phase refs were already on `PhaseDefinition` (PR1, value_objects.py:110), but the workflow-scope refs were only used at install time. PR2 therefore extends the create command, the `WorkflowTemplateCreatedEvent`, and the aggregate state with a `claude_plugins` list field. Legacy events without the field rehydrate cleanly: `_normalize_event_data` defaults the field to `[]`, and the apply-handler accepts both raw dicts (gRPC `GenericDomainEvent`) and `ClaudePluginRef` instances. This was the smallest additive change that allowed `_get_executable_phases` to union workflow-scope and phase-scope refs without re-parsing YAML at execute time.

2. **`ExecuteWorkflowCommand` is untouched** as instructed. Org/system scopes (#761) remain deferred.

3. **Resolver signature deviates slightly from the brief.** The brief specifies `resolve_for_phase(workflow_def, phase)`. The runtime has a `WorkflowTemplateAggregate` (and per-phase `PhaseDefinition`), not a `WorkflowDefinition` (the YAML model). Exposing the aggregate would force the resolver to depend on the orchestration aggregate type. Instead `resolve_for_phase(workflow_claude_plugins, phase_claude_plugins)` takes the two ref sequences directly. Functionally identical and decouples the resolver from the workflow loader.

4. **Materializer-side path-prefix.** Per the validation experiment plus the validated `inject_files()` shape, files land at `.syn-plugins/<plugin>/<rel_path>` (workspace-relative). The orchestrator emits `--plugin-dir /workspace/.syn-plugins/<plugin>` flags via `_build_provision_result`. These compose with the entrypoint-managed `AGENTIC_PLUGIN_FLAGS` rather than replacing them; the validation experiment confirms multiple `--plugin-dir` flags coexist cleanly.

5. **Resolver `LookupError` on missing lock entry.** The brief says "raise a clear error". A `LookupError` is unambiguous and will propagate up to the workflow dispatch handler. Errors at execute time should not happen because PR1's `ensure_registered` runs at workflow install + `global add` time, but the explicit raise prevents silent skip if the projection ever lags.

## E2E smoke

Authored at `docs/experiments/cycle-004/dogfood-platform-726/e2e-smoke-pr2.sh`. The script registers the validated `hello-world` plugin via the global add path, installs a one-phase workflow that declares it, dispatches the execution, polls for completion, then greps the session transcript for the sentinel `__SYN_HELLO_726__`.

Caveats:

- The script requires a fixture URL (`HELLO_WORLD_REF`) that the platform's git fetcher can clone. PR1's fetcher is a git-subprocess adapter; if `file://` URLs are not yet supported, push the `validation-experiment/hello-world/` tree to a throwaway repo or extend the fetcher's URL acceptlist. This is a smoke prerequisite, not a PR2 code gap.
- The agent must be able to authenticate (Claude OAuth or API key). `_build_agent_env` already handles both.
- The script is the canonical PR2 manual smoke; the unit and integration tests cover the materialization mechanics in isolation.
