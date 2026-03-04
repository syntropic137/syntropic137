# ADR-042: Event Type Naming Standard

**Status:** Accepted
**Date:** 2026-02-19
**Deciders:** Syn137 team

## Context

The event type constants across the observability pipeline had a consistent naming problem:
**Python identifier names did not match their string values.**

Examples before this ADR:
```python
# syn_shared/events/__init__.py
TOOL_STARTED   = "tool_execution_started"   # identifier ≠ value
TOOL_COMPLETED = "tool_execution_completed" # identifier ≠ value
TOOL_FAILED    = "tool_execution_failed"    # identifier ≠ value
PROMPT_SUBMITTED  = "user_prompt_submitted" # identifier ≠ value
NOTIFICATION      = "system_notification"   # identifier ≠ value
```

This caused real bugs:
- `ObservationType.TOOL_STARTED.value = "tool_started"` (domain enum) did NOT match
  `syn_shared.TOOL_STARTED = "tool_execution_started"` (infra constant), silently breaking
  projections that queried by event type.
- Import aliases like `EV_TOOL_STARTED = TOOL_STARTED` appeared to paper over divergence.
- Grepping for `tool_execution_started` in code produced no hits; grepping for `TOOL_STARTED`
  gave no indication of the stored value.

## Decision

**Python constant identifiers must exactly match their string values in SCREAMING_SNAKE_CASE.**

The string values are **canonical Claude Code hook event names** — we align to them, not the
other way around, because we cannot change what the Claude Code runtime emits.

### Convention

| Rule | Example |
|------|---------|
| Identifier = value in SCREAMING_SNAKE_CASE | `TOOL_EXECUTION_STARTED = "tool_execution_started"` ✅ |
| String values come from Claude Code hook names | `"tool_execution_started"`, `"session_started"` ✅ |
| No short-form aliases for hook event names | `TOOL_STARTED = "tool_execution_started"` ❌ |

### Renames applied

Python identifier renamed to match the unchanged string value:

| Old identifier | New identifier | String value (unchanged) |
|----------------|----------------|--------------------------|
| `TOOL_STARTED` | `TOOL_EXECUTION_STARTED` | `"tool_execution_started"` |
| `TOOL_COMPLETED` | `TOOL_EXECUTION_COMPLETED` | `"tool_execution_completed"` |
| `TOOL_FAILED` | `TOOL_EXECUTION_FAILED` | `"tool_execution_failed"` |
| `PROMPT_SUBMITTED` | `USER_PROMPT_SUBMITTED` | `"user_prompt_submitted"` |
| `NOTIFICATION` | `SYSTEM_NOTIFICATION` | `"system_notification"` |

All other event type constants already conformed (e.g., `SESSION_STARTED = "session_started"`,
`GIT_COMMIT = "git_commit"`, `TOKEN_USAGE = "token_usage"`).

### Single source of truth

`packages/syn-shared/src/syn_shared/events/__init__.py` is the authoritative constant registry.
All producers (`agentic-primitives`) and consumers (`WorkflowExecutionEngine`, projections,
`ObservationType`) MUST use these constants. Direct string literals are forbidden.

### Enforcement

`test_event_type_consistency.py` enforces:
1. Every `agentic_events.EventType` value is in `syn_shared.VALID_EVENT_TYPES` (producer/consumer contract).
2. `syn_shared` named constants match the Literal union.
3. `ObservationType` values used in TimescaleDB writes are in `VALID_EVENT_TYPES`.

The `_RESERVED_OBSERVATION_KEYS` guard in `AgentEventStore.record_observation` prevents
user-supplied data keys from colliding with event metadata (e.g., the `"message"` crash class).

## Consequences

- **Pre-production only**: String values are unchanged; DB records are unaffected.
  Only Python identifiers changed — no data migration needed.
- **~30 files updated**: The rename was mechanical (grep-and-replace) across packages.
- **Simpler code**: No more identifier/value divergence, no shim aliases needed.
  `ObservationType.TOOL_EXECUTION_STARTED` and `syn_shared.TOOL_EXECUTION_STARTED` are
  the same constant pointing to the same value `"tool_execution_started"`.
