# Issue 1398 implementation checkpoint

Checkpoint: 2026-09-22. Incomplete. Do not close issue 1398 or treat this as release-ready.

## Follow-up after draft PR creation

Draft PR #1401 contains the initial Syntropic137 checkpoint. Its pre-push
preflight failed on unpublished `apss-session-capture==2.1.0`; the local hook
was bypassed to publish the explicitly incomplete draft. Upstream dependencies
remain unpublished. The agentic-primitives gitlink now references the published
checkpoint commit described below; released image pins remain unchanged.

The subsequent local follow-up moves Python capture receipts into the APSS
contract and replaces Syntropic137's duplicate model with that shared type.
Rust and Python now consume common receipt acceptance/rejection fixtures,
including wrong namespaces, original hashes, malformed stored hashes, duplicate
acknowledgements and invalid field types. Python contract tests (4), Rust
inventory tests (6), and focused Syntropic137 adapter tests (22) passed.
APSS repository validation reported zero errors and warnings. This does not
establish full integration or published dependency availability.

The APSS contract is now committed as `d8924a557cfb114534f4cdb69ed1535f0eec4c8f`
in [upstream draft PR #139](https://github.com/AgentParadise/agent-paradise-standards-system/pull/139).
It adds isolated Python sdist/wheel validation to `just check` and a Python
3.11/3.14 CI matrix. Full local APSS `just check` passed after correcting two
Clippy module-order violations. Local validation included unrelated topology
changes that were excluded from the commit; hosted CI must verify the committed
tree. APSS 2.1 remains unpublished.

## Scope remains unchanged

Deliver workflow-run session discovery and centralized relationship reconstruction across Syntropic137 and required upstream repositories, including integration tests, coordinated dependencies and releases, and a PR that closes #1398 only after the complete acceptance matrix is proven. The governing plan is `workflow-run-session-discovery-plan.md` in the parent workspace.

## Coordinated review artifacts

- Main draft: https://github.com/syntropic137/syntropic137/pull/1401
- Agentic primitives: https://github.com/AgentParadise/agentic-primitives/pull/418,
  pinned here at `eabd93bccc6b74f47f64fd83df4ed2c802f1f02d`.
- APSS contract: https://github.com/AgentParadise/agent-paradise-standards-system/pull/139
- Exporter: https://github.com/AgentParadise/agentic-session-exporter/pull/24
- SeshMagic: https://github.com/seshmagic/seshmagic_session_store/pull/55

These are draft checkpoints, not release delivery. Agentic-primitives includes
local Codex hook installation and durable child-journal recovery transport.
Live pinned-harness execution, Claude child hooks and complete acceptance remain
unverified. Its full QA currently stops on stale locks outside session-store.

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

Next verify installed hooks with pinned harness execution, then complete verified child phase/attempt attribution and the remaining acceptance matrix. Isolated green tests do not prove the full feature.

## Per-attempt dispatch identity checkpoint

The phase dispatcher now supplies `AGENTIC_INVOCATION_ID` and
`AGENTIC_ATTEMPT_ID` only after the session repository saves the registration.
Each capacity retry gets its own pair. Dispatch copies the launch environment,
removes inherited values, and leaves the shared launch environment unchanged.
These are runtime context values, not operator settings. Their names are
centralized in `syn_shared.env_constants`.

Validation: 60 lifecycle, retry-dispatch and workflow-processor tests passed;
focused Pyright passed with zero errors or warnings. The new cases cover Claude
and Codex retries, stale identity removal without a repository, and failed
registration preventing handler dispatch. Log:
`/private/tmp/1398-invocation-dispatch-tests.log`.

This establishes the top-level handoff only. Native child hooks do not yet
consume the context, and no native-child completeness guarantee is claimed.

## Child journal ingestion checkpoint

The agentic-primitives worktree now contains durable child hook observations,
immutable change pages, read-only export and a validated workspace reader.
Syntropic137's `session_inventory/child_journal.py` translates those observations
into the existing evidence journal, returning page progress only after every
append succeeds. Hook observations carry corroborated lineage/binding evidence;
they do not claim host registration, coverage, capture bodies or membership.

A depth-three adapter-to-resolver test verifies immediate-parent edges, exact
native bindings and order-independent reconstruction. The focused drain plus
existing relationship suites pass 27 tests. This is not a pinned-harness test.

Remaining wiring constraints found during inspection:

- `CaptureRecoveryWorker` and `session_capture_spools` currently have only the
  transcript-envelope cursor. Child changes require an independent durable
  cursor with the same lease fencing; never reuse the envelope sequence.
- The resolver transfers explicit membership through identity bindings, not
  arbitrary lineage edges. An earlier adapter comment overstated propagation
  and was corrected. Phase/attempt attribution for child observations still
  requires a verified invocation-context join or explicit segment-aware rule.
- Hooks are not installed in the workspace image. Missing child journals must
  remain explicit gaps, not empty-success evidence.

Independent child cursor storage is now implemented on `session_capture_spools`.
`advance_children` checks the live lease token plus prior child cursor, updates
only child progress and leaves the lease held for transcript work. Claims recover
both cursor domains. Additive schema migration preserves existing envelope work.
Two real PostgreSQL integration tests pass, including independent cursor restart,
stale writer fencing and incomplete traversal rejection. Five focused worker/drain
tests and focused Pyright/Ruff also pass. Worker invocation of child reads and
hook installation remain outstanding.

The runtime now supplies `ChildJournalDrain` to `CaptureRecoveryWorker`.
`DockerSpoolRecovery` exposes both readers from the same retained-volume helper.
The worker persists a child page before advancing its independently fenced cursor;
an unreadable journal retains that cursor, logs failure and does not block already
durable transcript progress. Pending child pages request immediate subsequent
work. Six worker/drain tests and focused type checks pass. Installed hooks and a
real image-level child capture/recovery acceptance run remain unverified.


Latest main validation: 229 selected session/inventory/attempt tests passed;
repository-wide Pyright reported zero errors and 16 optional-dependency warnings.
The full QA result is recorded separately and must not be inferred from these
focused checks. Main includes the published AP source commit, but its workspace
image still requires the coordinated build/release/pin update.

The subsequent full `qa-ci` run reached topology fitness and found cognitive/
cyclomatic violations in LocalTranscript and InventoryItem. Those components
were refactored by separating archive validation/loading, preview rendering and
capture-row rendering. Targeted fresh topology reports all functions in both
files below existing thresholds: LocalTranscript cognitive/cyclomatic 4/4;
InventoryItem 7/8; the maximum across their helpers is cognitive 8, cyclomatic 8.
No thresholds or exceptions changed. Eight focused UI tests and TypeScript pass.
Full dashboard CI passed after the refactor: 41 files, 324 tests, lint (one existing
warning), TypeScript and production build. Log:
`/private/tmp/1398-dashboard-refactor.log`. Repository-wide QA must still be rerun.
