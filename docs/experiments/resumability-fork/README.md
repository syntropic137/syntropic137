# Fork resumability experiments

Four experiments behind ADR-014 section 7. They measure CURRENT behaviour; none
of them assumes a fork implementation exists.

Recovered from `refs/syn/lost/exec-c8acee7794dc/experiment`. The phase that
wrote them was failed by the unpushed-work guard for leaving them uncommitted,
which is the only reason they survived the workspace teardown.

| file | question | result |
|---|---|---|
| `test_exp1_concurrent_append.py` | Do optimistic concurrency and `NoStream` each admit exactly one writer? | YES. 200 concurrent races, `overlapped=0`, one winner plus `ConcurrencyConflictError` / `StreamAlreadyExistsError` every time. Dropping `expected_version` gives two winners, so the guard is load-bearing. Also: `stream_exists` returns `False` when the store is UNREACHABLE - a fail-open. |
| `test_exp2_foreign_artifact_ids.py` | Can an execution reference another execution's artifact ids and have the read paths serve them? | **NO.** The parent's own next phase gets 2 injected files; a fork holding the same artifact id gets `[]`. `get_by_id` still returns the content. Relinking the row to the fork restores injection, identifying the read path rather than the id as the constraint. |
| `test_exp3_prompt_from_started.py` | Is the original prompt recoverable from `WorkflowExecutionStartedEvent` alone? | PARTLY. Task and inputs round-trip byte-identically. The RENDERED prompt does not: re-rendering with the fork's id differs from the parent by exactly that id, and the template text is not in the event. |
| `test_exp4_cancelled_resume.py` | What does the system actually do when a CANCELLED execution is resumed? | The aggregate refuses all twelve commands on a rehydrated cancelled execution. The HTTP resume controller decides from the detail PROJECTION, never loads the aggregate, and returns success on a stale `paused` row - a fail-open on the route a terminal-state guard would live on. |

## Running them

```
uv run pytest docs/experiments/resumability-fork -q -s
```

They print their measurements; `-s` is the point. `exp1` and `exp3` also accept
`EXP_GRPC_ADDR` to run against the real Rust event store over gRPC rather than
the in-memory client, which is what makes the concurrency result mean something
beyond a single process.

They live under `docs/experiments/` rather than a package test directory on
purpose: they are a record of what was measured on 2026-09-26, not a suite the
build must keep green. Two of them assert facts that SHOULD change once the
fail-opens above are closed.
