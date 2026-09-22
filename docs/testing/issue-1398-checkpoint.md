# Issue 1398 implementation checkpoint

Checkpoint: 2026-09-22. Incomplete. Do not close issue 1398 or treat this as release-ready.

## Scope remains unchanged

Deliver workflow-run session discovery and centralized relationship reconstruction across Syntropic137 and required upstream repositories, including integration tests, coordinated dependencies and releases, and a PR that closes #1398 only after the complete acceptance matrix is proven. The governing plan is `workflow-run-session-discovery-plan.md` in the parent workspace.

## Current worktrees

| Repository | Branch | Git status entries at checkpoint |
| --- | --- | ---: |
| Syntropic137 | codex/1398-session-discovery | 146 |
| agentic-session-exporter | codex/1398-local-capture | 28 |
| seshmagic-session-store | codex/1398-run-inventory | 50 |
| agent-paradise-standards-system | codex/1398-inventory-profile | 19 |
| agentic-primitives | codex/1398-session-evidence | 24 |

Counts include untracked directory entries, not recursive file counts. Tracked diff statistics exclude new untracked files. Changes are still uncommitted; no release delivery is established by these working trees.

## Implemented paths, with limits

- Local spool acquisition, immutable byte archive, capture catalog, evidence journal, relationship reconstruction and revision-pinned inventory reads exist.
- Inventory and capture delivery use durable jobs and exporter outboxes. Remote receipts are historical acceptance evidence, not proof of current body access.
- Optional replication has independent task supervision in adapters. Domain replay advances checkpoints without starting delivery.
- SeshMagic has qualified capture identities, immutable versions and replicated inventory queries. Full legacy migration and deletion semantics remain incomplete.
- Local transcript reads resolve an exact archive hash within source/run/harness/native identity. A new API route, CLI command and dashboard preview/download use that path.
- Local authorization currently follows ADR-059's installation-wide gateway boundary. The new policy checks source identity and durable object revocation. It is not per-user authorization. Revocation does not physically erase bytes or propagate to replicas.
- Qualified pricing dispatch exists only when capture producers supply the optional identity collection. Producers do not yet populate it. Leader exclusion and billing ledger still use bare IDs.

## Validation evidence

Logs below are local checkpoint artifacts, not committed CI evidence. Later changes invalidate broad claims unless the affected checks are repeated.

- Python CI target passed with 79% aggregate coverage, six skips and two expected failures: `/private/tmp/1398-unit-ci.log`. This run predates the newest transcript handler/API/UI additions.
- Architecture invariants passed: `/private/tmp/1398-fitness-invariants.log`. This run also predates the newest transcript additions.
- Repository-wide Pyright: zero errors, 16 warnings: `/private/tmp/1398-pyright-latest.log`. New transcript modules received focused type checks afterward.
- CLI, OpenClaw, dashboard and documentation CI passed before the latest transcript clients: `/private/tmp/1398-client-ci.log`.
- Latest dashboard CI passed, including build and tests: `/private/tmp/1398-dashboard-transcripts.log`.
- New CLI transcript command: nine focused tests and TypeScript passed. Contracts/docs regenerated: `/private/tmp/1398-transcript-cli-codegen.log`.
- Real PostgreSQL/filesystem local revision, history and revocation integration passed: `/private/tmp/1398-local-read-integration.log`.
- Full `just qa-ci` is not green as a single run. The attempted run stopped on formatting, subsequently fixed. Preflight's generated environment check compares uncommitted generated files with HEAD.
- Validation uses locally prepared unpublished APSS dependencies with `UV_NO_SYNC=1`. Released dependency resolution and lockfiles are not proven.
- Existing workspace image pins passed their gate, but they still identify the previously released image. This does not deliver the new agentic-primitives changes.

## Required remaining delivery work

1. Finish supported native-child hooks and cross-harness launch instrumentation, resume/fork segments, descendant settlement and the depth-three acceptance matrix.
2. Finish historical evidence acquisition/backfill, verified legacy aliases and reconstruction provenance without fabricated completeness.
3. Complete canonical transcript identity/detail routes, session-to-run navigation, filtering, browser QA and full client behavior. Current run-scoped archive access is only part of this requirement.
4. Populate verified qualified pricing identities and migrate ledger/leader identity safely, with collision and cumulative-resume billing regressions.
5. Complete deletion/expiry/retraction behavior across local storage, delivery, remote storage and historical readers; add quotas and retention cleanup.
6. Finish same-harness restore coverage, including Codex and real remote round trips.
7. Complete APSS/shared-package publication, exporter/AP releases, actual dependency locks, API exporter installation and new workspace image pins.
8. Run the complete acceptance matrix and final repository gates against the final coordinated dependencies. Then prepare reviewable commits and upstream/main PRs. Do not close #1398 for a partial vertical slice.

## Next checkpoint

First produce an acceptance-to-code/test map and a coherent review package from the existing five worktrees. Avoid treating isolated green tests as proof of the full feature. The next implementation batch should target a named missing acceptance item and end with its end-to-end evidence.
