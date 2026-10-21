# Plan: provider-neutral agent execution (Docker + E2B + OpenSandbox)

Status: orchestrator plan, 2026-10-13. Input: the five `docs/research/2026-10-12-*` documents, revalidated against `main` 4d497c4a5 (AW 5c4e559). Targets: [north-star.md](../north-star.md) 100, then 1,000.

## Recommendation

Finish the machinery that exists; add no new queue, scheduler or parallel provider path.

1. **Executor split first (#1310 Phase 1, ADR-072).** The durable `ExecutionRunQueue` port + Postgres adapter exist; nothing in `apps/` consumes them. Land 1.3 (#1808), then 1.4 run-scoped fold, then 1.5 `ExecutionHost` claim loop. Placement and remote pools hang off the claim, so this is the trunk.
2. **One provider contract, on the production surface.** Production runs the Python `agentic_isolation` provider (`agentic/adapter.py`); the Rust `WorkspaceProvider` is not used in production. Extending only the Rust trait would be a parallel path. The contract is defined in APSS (language-neutral schema + conformance), implemented first where production runs, and the Rust trait conforms to the same schema. See decision D1.
3. **Remote boundary before any remote pool:** durable attempt/resource/operation identity, terminate-confirm-before-retry, reachable credential broker (#1735), remote capture spool profile.
4. **Then E2B beside Docker** (#350) with execution-level pool selection in the claim transaction, then OpenSandbox as adapter and, separately, as transport.
5. **Measure throughout:** token-free load driver (#1717) and per-phase profile (#1716) before claiming any tier.

## Revalidated gaps (main 4d497c4a5)

All P0 rows of the research gap table are still open. Changes vs the research text:
- `SYN_EXECUTION_RUN_QUEUE_ENABLED` exists only on unmerged #1808. Only ADR-072 step 1.2 (port + adapters) has landed.
- `execution_budget.backend` column exists, unread: the natural pool key.
- Reusable: `WorkspaceHandle.provider_reference`, Python `SupportsWorkspaceLogs` / `SupportsStagedTeardown`, `SpoolRecoveryPort` / `SpoolReleasePort`, `preserve_interrupted_run`, `SidecarPort`, `CloudProvider` settings stubs.
- `docs/research/2026-10-08-remote-executor-e2b.md` line 39 ("no ExecutionRunQueue exists") is stale.

## Dependency-ordered work

| # | Work | Repo / owner | Depends on | Exit evidence |
|---|---|---|---|---|
| A1 | Land #1808 (1.3 start-only admission, flag off) | syn | - | reverified at a head merged with main; flag-off path unchanged |
| A2 | 1.4 run-scoped to-do fold | syn | A1 | fresh processor replays a claimed run to the same events |
| A3 | 1.5 `ExecutionHost` claim loop + executor entrypoint | syn | A2 | API restart leaves executor running; SIGKILL enters reconciliation |
| B1 | Contract map: every APSS EXP-V1-0006 MUST -> Docker (Python) + Rust status; COVERAGE.md rows | AW + APSS | - | no MUST unmapped; unsupported policy refused, tested |
| B2 | Operation contract: preflight/provision/hydrate/start/status/observe/cancel/finalize/destroy; opaque WorkspaceRef + OperationRef; typed status/result/error; bounded observation page with cursor + gap | APSS schema (versioned) + AW Python protocol + Docker impl | B1 | conformance suite passes on Docker; start returns a ref, never buffers the run |
| B3 | Recipe tool requirements: installed binaries/services vs MCP access vs harness allow/deny; credential refs only | AW recipe | B2 schema shape | same recipe compiles for claude and codex; no raw secret in manifest (test) |
| C1 | Attempt/resource/operation identity on the run queue; ambiguous-create reconciliation; terminate-confirm-before-retry; ADR-072 amended in place | syn | A3, B2 | lost-response create reconciled, never redispatched |
| C2 | Reachable authenticated credential broker, execution-scoped grants, expiry/revocation | syn (#1735) | B2 | sandbox holds no raw Claude/Codex/GitHub credential |
| C3 | Remote capture spool profile + recovery impl; durable finalize before destroy | AW + syn | B2 | failed upload leaves recoverable output |
| D1 | E2B provider + E2B pool; compatible-pool selection in the claim; per-pool budget | AW + syn (#350) | A3, C1-C3 | same recipe runs on Docker and E2B pools at once; incompatible requirement refused before start |
| D2 | OpenSandbox adapter, then execd-as-transport comparison | AW | D1 | same suite passes; choose smaller implementation by measurement |
| M1 | Token-free load driver + stub agent (#1717) | syn + AW | - (A3 for deploy-survival) | `--n 20` report on a beta; `--n 100` runs |
| M2 | Usage records: workspace time/shape, warm capacity, failed attempts, storage, snapshots, transfer; priced in syn | syn | D1 | `compute_cost_usd` non-zero with provenance |

Parallel lanes: A (trunk), B (contract), M1 (measurement) start now. C waits on A3+B2. D waits on C.

## Fault tests (C and D exit criteria)

accepted request with lost response; lease expiry with a live agent; worker SIGKILL; stream disconnect; cancel during readiness and during finalize; credential expiry; provider 429; final-upload timeout; destroy failure; log/snapshot retention expiry; old warm-pool generation publishing during rollout. Assert: no blind redispatch, no stale-owner terminal commit, retained output readable, reservation released exactly once, leaked cleanup discoverable, healthy pools unaffected.

## Decisions (owner; defaults taken, not blocking)

- **D1 contract surface.** Default: APSS schema is the contract; first implementation in the Python production provider; Rust trait brought to the same conformance. Alternative: move production to Rust (bigger, separate decision).
- **D2 credentials in remote sandboxes.** Default: none until C2. No E2B run carries Claude/Codex/GitHub tokens before the broker exists.
- **D3 E2B account.** Needed for D1. Until provided, D1 runs only against a contract double.
- **D4 live adoption.** Default: no (ADR-072 no-reattach stands); terminate-confirm-before-retry.
