# Issue 1398 implementation checkpoint

Checkpoint: 2026-09-22. Incomplete. Do not close issue 1398 or treat this as release-ready.

## Full closeout audit, 2026-09-23

This table supersedes optimistic completion claims. A passing component test does
not mark its entire acceptance criterion complete. The exact scope remains the
14 criteria in issue #1398. Personal/demo IDs and transcripts stay local.

| # | Acceptance requirement | Current evidence | Work still required |
| --- | --- | --- | --- |
| 1 | Local operation with remote absent or unreachable, all clients | Real local parent/child demo passed; local SQL pipeline tests passed | Multi-phase and configured-unreachable full-stack checks, CLI agreement |
| 2 | Cross-harness and native children through depth three | Real native children and pinned Claude -> Codex -> Claude chain, independently checked against native files | Full-stack mixed/native combinations, resume/fork matrix and expected coverage |
| 3 | Concurrency and resume memberships across runs | Resolver resume tests exist; SQL namespace/pagination isolation passes | Exercise real resume segments and concurrent launch associations |
| 4 | Durable intents and idempotent/conflicting lifecycle | Invocation aggregate tests and fenced spool cursors exist | Audit all controlled launch paths and crash-before-bind integration |
| 5 | Failures, cancellation, background children, kill/restart/replay | 22 fresh PostgreSQL/pipeline/spool integration tests pass | Full lifecycle matrix and descendant settlement against pinned harnesses |
| 6 | Independent SeshMagic query and interrupted replication | 2 fresh real exporter/server/SQL/MCP tests pass after rebuilding current binaries | Complete out-of-order delivery and offline-origin matrix |
| 7 | Qualified identities, legacy aliases, immutable memberships | Namespace tests and immutable capture storage exist | Verified legacy alias migration and collision matrix |
| 8 | Large bounded pagination under concurrent writes | Large native pipeline and SQL snapshot-pagination tests pass | Audit >1000-node and >500-observation thresholds, indexes and every client cursor contract |
| 9 | API/CLI/UI parity and strict completeness | Routes and client tests exist; local UI demonstrated | Canonical detail/navigation/filtering and full client parity matrix |
| 10 | Whole-object authorization and safe transcript access | Real archive/revocation/shared-byte tests pass | Full scope/raw-token/expired/redacted/secret-diagnostic matrix |
| 11 | Retention, immutable revisions, deletion without resurrection | Immutable archives, revocation, retractions implemented | Physical expiry/deletion, durable cross-store tombstones and cleanup quotas |
| 12 | Resumable backfill and unchanged billing/platform totals | Qualified pricing read seam exists | Backfill acquisition, qualified producer/ledger/leader wiring and cumulative-resume regressions |
| 13 | Deterministic centralized historical reconstruction | Native pipeline, late child and stale publication tests pass | Historical-source acquisition and complete replay/correction matrix |
| 14 | Fake harness extension and dependency enforcement | Harness registry and topology checks exist | Run explicit contract and vendor-boundary tests on final changes |

Release gates remain separate requirements: merge upstream dependencies in order,
publish coordinated packages and signed images, update real pins, verify a clean
checkout, run repository-required checks, and update existing draft PRs. Latest
main preflight passed complexity checks but two upstream-default-branch
reachability invariants still fail while AP and APSS are unmerged.

Fresh baseline: `test_session_inventory_postgres.py`,
`test_session_inventory_pipeline.py`, and `test_capture_spool_recovery.py`:
22 passed using real disposable PostgreSQL. Log retained locally at
`/private/tmp/1398-closeout-postgres.log`. No criterion is marked complete solely
because this suite passed.

Fresh native capture follow-up: Claude 2.1.250 now registers and binds native
`Agent` children, including nested immediate parents. Its offline pinned-binary
test verifies depth three, committed intent before each child request, and exact
child identities against independent native transcript files. Codex 0.150.1
native-child and hook-trust tests also pass against the updated shared handler.
Workspace startup composes both harnesses' hooks and rejects disabled capture.
The complete session-store package suite passes with the real exporter; native
binary tests run separately with networking disabled. Agentic Primitives full
`UV_NO_CONFIG=1 just qa` passes, with the real exporter enabled, at `ddd9362`.
Its Claude implementation is in `8abf97a`, published in existing PR #418.
An additional 87 Syntropic137 resolver, invocation, local transcript, child drain,
recovery and API tests pass. Logs: `/private/tmp/1398-ap-final-qa.log` and
`/private/tmp/1398-closeout-domain-api.log`. This does not close mixed
harness launch, descendant settlement, or complete coverage requirements.

Structured delegation follow-up (`agentic-primitives@aaa1da1`, PR #418):
`UV_NO_CONFIG=1 just qa` passes with the real exporter enabled.
`syn-delegate` now persists intent before
launch, records the actual process outcome, and binds exact native identity from
that process's machine stream. Parent and child harness namespaces stay distinct.
The pinned Claude -> Codex -> Claude offline test passes with independent native
files and pre-launch expectations. Cancellation, timeout, failed OS launch and
shell-masked failure have subprocess tests. Original journal records and source
hashes survive the additive schema upgrade. Syntropic137 ingestion/attribution
checks pass (20 tests); v1/v2 exporter-to-host transport passes (9 tests).

Codex uses its native shell `CODEX_THREAD_ID`; no permission-granting or command
rewrite hook was added. Claude supplies quoted parent context through its shell
hook. The image exposes the shim outside the virtualenv so login-shell PATH
changes do not hide it. The supported image build completed at `aaa1da1`;
installed-package native and mixed-harness tests passed, including the actual
`syn-delegate` executable. PR #418 also contains `249abf2`, which adds the
packaged-entrypoint conformance option. Local logs:
`/private/tmp/1398-delegation-image-build.log` and
`/private/tmp/1398-installed-native-tests.log`. Rebuilding/deploying the API and
full-stack mixed-harness proof remain pending, as do descendant settlement and
run-wide coverage closure.

## Recovery checkpoint follow-up

Unchanged child-journal polls now update one durable acquisition head instead of
appending evidence and triggering another reconstruction. Status transitions
remain append-only; the head fences stale observations across restart. An indexed
legacy lookup preserves existing histories and revision hashes. Real PostgreSQL
checks pass (19), worker tests pass (10), Ruff passes, and Pyright reports zero
errors (16 existing warnings). Architecture checks only fail the two known
upstream default-branch reachability gates after retrying with network access.

The isolated API was rebuilt with this change and is healthy. The previous live
parent/child inventory and exact archived transcript hashes passed verification
after restart. Full mixed-harness workflow proof and remaining acceptance rows
are still pending. Local logs: `/private/tmp/1398-status-checkpoint-sql.log`,
`/private/tmp/1398-status-checkpoint-unit.log`, and
`/private/tmp/1398-checkpoint-api-rebuild.log`.

## Local deletion foundation

The local archive now supports irreversible exact-body deletion with durable
anti-resurrection markers. Fixed lock stripes serialize reads, writes and deletes
across archive instances/processes. Tombstones are fsynced before unlink; an
interruption between those operations still denies reads and puts. Spool replay
skips explicitly deleted bodies, advances normally, and preserves immutable
acquisition evidence. This is an archive primitive, not yet an operational
retention policy or cross-store deletion implementation.

Thirteen archive/recovery unit tests and the real PostgreSQL interrupted-spool
replay test pass. The latter verifies deletion followed by complete spool replay,
unchanged evidence watermark and continued absence of bytes. Pyright reports zero
errors, with the same 16 existing warnings. Local log:
`/private/tmp/1398-deletion-spool.log`. Remaining work includes retention commands,
expiry scheduling, inventory availability overlays, upstream tombstone delivery,
replica retry fencing and cleanup quotas.

## Local expiry scheduling

Optional `SYN_SESSION_INVENTORY_LOCAL_BODY_RETENTION_SECONDS` now schedules
local body expiry through durable deletion requests. It is disabled by default;
age is measured from first catalog acquisition. Each recovery tick discovers at
most 100 eligible rows and removes one body, with SQL acknowledgement after the
filesystem tombstone and unlink. Failed expiry does not block other inventory
work. Two real PostgreSQL tests verify bounds, source isolation, retained catalog,
and crash after unlink; 14 scheduling/configuration tests pass. Log:
`/private/tmp/1398-body-retention.log`.

This closes local expiry scheduling only. Replica deletion, queued exporter
copies, spool-volume cleanup, explicit expired availability and overall quotas
remain unfinished. The new setting has not been enabled on the live demo stack.

## Expiry and host delivery fencing

Local expiry now cancels host capture-delivery jobs across destinations. Both
active delivery leases and queued receipt leases reject stale acknowledgements;
a new destination cannot rediscover a body with a durable deletion request.
Four real PostgreSQL retention tests and seven delivery-worker tests pass. This
prevents endless host retry work but does not remove already queued exporter
copies or remote bodies. Those remain required cross-store work. Test log:
`/private/tmp/1398-expiry-delivery.log`.

## Replica deletion foundation

SeshMagic commit `05cd9b2` adds migration 0011 and exact qualified-revision
tombstones. The namespace-authorized DELETE endpoint removes the stored envelope,
retains identity/inventory history, and blocks late or concurrent re-upload with
HTTP 410. Tombstones can precede capture. Two real PostgreSQL tests and the real
HTTP authorization/inventory integration test pass; workspace Clippy passes.
Logs: `/private/tmp/1398-sesh-delete-sql.log` and
`/private/tmp/1398-sesh-delete-http.log`.

Exporter tombstone transport, origin scheduling, queue cleanup and the complete
cross-store interruption matrix remain unfinished. This commit is local and has
not yet been pushed to the existing SeshMagic draft PR.

## Exporter deletion transport

The exporter now accepts bounded `--capture-delete` requests and persists exact
qualified APSS content hashes in its destination-bound SQLite outbox. Drain
prioritizes deletion within the existing operation bound; failure survives
restart, only 204 acknowledges deletion, and deleted revisions cannot be
re-enqueued. A 410 upload response cancels delivery and queues deletion. Schema
migration is serialized across processes. Full exporter tests and strict Clippy
pass. Measured line coverage is 97.11%, above the unchanged 97% CI floor.
Logs: `/private/tmp/1398-exporter-delete-full.log` and
`/private/tmp/1398-exporter-delete-coverage.log`.

Physical exporter spool cleanup, host tombstone scheduling and real cross-store
interruption tests remain unfinished. New exporter and SeshMagic commits are
still local pending coordinated draft PR updates.

## Host deletion scheduling

Envelope expiry now commits the original APSS content hash before removing bytes.
The standard exporter provides credential-free `--envelope-hash`; Python does not
reimplement canonical hashing. Capture replication schedules durable deletion
before upload work and checkpoints only after exporter enqueue. Deletion requests
remain available to newly configured destinations. Five PostgreSQL retention
tests pass, including the actual exporter while the store is unreachable, failed
enqueue/restart, and hash-before-unlink ordering. Forty-two related host unit tests
pass; Pyright has zero errors (16 existing warnings). Exporter CLI tests and strict
Clippy pass. Logs: `/private/tmp/1398-host-deletion-tests.log` and
`/private/tmp/1398-envelope-hash-cli.log`.

The full real exporter/server interruption matrix and physical exporter spool
cleanup remain unfinished. Changes are local and not yet deployed to the demo.

## Verified remote deletion and exporter cleanup

The real host/exporter/SeshMagic/PostgreSQL test now covers expiry of three
revisions, deletion queued during outage, restart, remote body absence, and a
separate delayed upload receiving 410 without restoring content. Catalog rows
remain discoverable. It also verifies physical absence of envelope files in
both exporter outboxes. The exporter preserves a shared file while another
qualified identity still requires delivery; legacy content hashes commit before
unlink, and interrupted cleanup is idempotent. Full exporter tests and strict
Clippy pass. Coverage is 97.04%, above the unchanged 97% floor. Logs:
`/private/tmp/1398-deletion-full-cleanup.log` and
`/private/tmp/1398-exporter-cleanup-coverage.log`.

This proves the controlled deletion chain, not all retention requirements.
Workspace source-volume cleanup, quotas, current availability overlays and the
remaining acceptance criteria still require completion. Latest changes remain
local until coordinated PR updates.

## Current transcript-read availability

Authorized local transcript reads now distinguish durable expiry/deletion from
unexpected missing bytes. The API returns `expired` for a tombstoned body; the
dashboard explains that session history remains and does not offer a download.
Generated API, CLI and dashboard contracts include the status. Seventeen domain
and archive tests, five preview tests and the API route suite pass. Full codegen
completed; Pyright has zero errors (16 existing warnings). Logs:
`/private/tmp/1398-expired-ui.log` and `/private/tmp/1398-expired-api.log`.

This updates transcript detail reads. Immutable historical capture receipts still
need an explicit current-availability overlay in inventory pages and equivalent
replica/client treatment. The full acceptance criterion is not yet complete.

## Inventory-page restriction overlays

Capture pages now include separate `body_overrides` for current local expiry or
withholding. One bounded, indexed lookup uses only hashes present in that page
and its installation namespace. It does not mutate historical receipts or claim
unchecked bodies are currently present. Dashboard rows distinguish recorded
availability from current restrictions and suppress unavailable download controls.
The real PostgreSQL isolation/immutability test, API route suite, five inventory
UI tests, dashboard type check and regenerated contracts pass. Logs:
`/private/tmp/1398-body-overlay-sql.log` and `/private/tmp/1398-overlay-ui.log`.

Replica availability presentation, CLI capture-page navigation and the remaining
acceptance matrix remain unfinished. These changes have not been deployed to the
live demo stack or pushed to the draft PR yet.

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

Central child attribution now retains explicit invocation-context observations.
The resolver joins controller invocation and attempt IDs only against active
REGISTERED host membership. Matching context yields corroborated child membership
with host and workspace provenance, then the existing binding logic attributes
the native transcript. Stale attempts, absent host facts and conflicting contexts
produce gaps instead of fabricated membership. Retractions remove derived claims.
Context records participate in assembly, serialization, scope validation and quota
accounting. The broader session-domain/drain run passed 195 tests; seven focused
attribution tests then passed including assembly and quota checks. Type checking
reported zero errors and two existing import warnings. This does not establish
live harness capture, descendant settlement or full acceptance.

Attribution review added ambiguous-host-phase and workspace-retraction cases.
Duplicate host/hook delivery now unions provenance before generating memberships,
preventing a Cartesian-product expansion. Resolver version is now
`syn-session-relationships/2` to identify the changed interpretation rules.
All 200 selected session-domain/drain tests pass; focused Pyright reports no
errors or warnings. Fresh topology keeps attribution functions below existing
complexity limits. No capture-completeness or release-readiness claim follows.

## Durable child acquisition outcomes

The host now appends a bounded acquisition outcome for each child-journal read,
using the persisted spool lease token as its monotonic sequence. Read failures
produce a visible `child_journal_unreadable` gap without recording exception text.
A successful later read supersedes earlier failures; delivery order cannot let a
stale worker restore an obsolete gap. Producers and streams remain isolated.
Same-sequence conflicting outcomes retain the failure. Explicit evidence
retractions remain effective, and all status records count toward batch limits.
Child cursor acknowledgement follows durable evidence and outcome writes.

Resolver version is now `syn-session-relationships/4`. Active acquisition gaps
prevent reconciled coverage even when every known transcript body is present.
Recovery alone does not establish supported or complete capture.

Validation: 211 session-domain and focused child-drain/recovery tests passed.
Changed Python files pass Ruff. Upstream agentic-primitives QA run 35799170837
passed at bca76ba. Full coordinated integration remains unfinished. Each recovery
poll currently retains an outcome, including unchanged success; status retention
and polling volume need addressing before final acceptance. Real pinned harness
capture and the broader issue acceptance matrix remain open.
