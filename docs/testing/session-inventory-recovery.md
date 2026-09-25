# Session inventory recovery tests

The Docker recovery test needs a workspace image containing the coordinated
agentic-primitives local capture provider and an exporter with `--spool-only`,
`--spool-list`, and `--spool-read`. An older published image cannot exercise this
contract. Build the changed upstream sources into a local workspace image, then run:

```sh
SYN_CAPTURE_TEST_IMAGE=your-local-capture-image:tag uv run pytest \
  packages/syn-adapters/tests/test_docker_capture_recovery.py -m integration
```

The test explicitly enables local-image verification for its process. Recovery
still resolves that local image to an immutable Docker image ID. Production uses
the normal workspace signature and digest policy.

The test creates a named volume, starts the local capture capability, writes a
native transcript, kills the workspace before finalization, and removes the
workspace. It then runs the real exporter in a network-isolated recovery helper,
drains the envelope into the host archive and PostgreSQL journal, and checks exact
native bytes. A second recovery must not add another revision merely because its
helper has a different hostname. A missing-volume test proves recovery does not
manufacture an empty replacement. Test cleanup removes only its own volume.

The following tests cover separate failure boundaries:

```sh
uv run pytest packages/syn-adapters/tests/test_capture_spool_recovery.py \
  packages/syn-adapters/tests/test_session_spool_drain.py -m integration
uv run pytest packages/syn-adapters/tests/test_capture_recovery_worker.py -m unit
```

These verify cursor preservation across replay/restart, installation isolation,
expired-worker fencing, idempotent interrupted-page replay, and failure before
cursor acknowledgement. They do not establish native descendant completeness,
remote replication, or access-control coverage.

## Inventory exporter boundary

The host adapter invokes the standard Rust exporter. It does not implement HTTP
replication itself. `--inventory-enqueue` must acknowledge durable local storage;
`--inventory-drain` reports pending remote work separately. The adapter rejects
contradictory exit-code/receipt pairs and bounds process output and duration.

Run the Python subprocess tests with:

```sh
.venv/bin/pytest packages/syn-adapters/tests/test_inventory_exporter_transport.py -m unit
SYN_TEST_EXPORTER_BINARY=/absolute/path/to/apss-session-exporter \
  .venv/bin/pytest packages/syn-adapters/tests/test_inventory_exporter_transport.py -m integration
```

The integration test runs the actual Rust binary with APSS Python messages. It
checks durable enqueue, restart deduplication, and retained work after a failed
upload. It does not prove remote SeshMagic publication or production scheduling.
The APSS 2.1.0 Python package is currently installed from the adjacent development
worktree; published dependency pins and the lockfile still need coordination.

## Optional live replication

Set `SYN_SESSION_INVENTORY_REPLICATION_ENABLED=true`, the replica base URL in
`SYN_SESSION_INVENTORY_REPLICATION_STORE_URL`, and its namespace grant in
`SYN_SESSION_INVENTORY_REPLICATION_WRITE_TOKEN`. The grant must authorize this
installation's source ID and producer `syntropic137-inventory`. The configured
`SYN_SESSION_INVENTORY_EXPORTER_BINARY` must be an installed standard exporter
with inventory support. Ordinary transcript tokens do not grant this authority.

The existing durable recovery signal schedules the optional replication process
manager after replay. It supervises separate bounded enqueue and drain tasks;
neither task blocks the shared coordinator. At most one task of each kind runs
per API process. PostgreSQL leases fence enqueue progress across processes.
Drain retries up to 50 operations per signal, within the subprocess timeout.
Failed or interrupted operations remain in the exporter outbox.

The outbox is under the persistent inventory archive directory, partitioned by
destination and source hashes. Preserve this directory when restarting the API:
a PostgreSQL checkpoint means operations reached that durable outbox, not that
SeshMagic acknowledged them. Deployments sharing one source identity must share
the same persistent outbox. Never move an enqueue checkpoint to a host that lacks
its outbox. Changing a destination starts a separate export checkpoint.

Scheduling, settings, and subprocess compatibility are verified separately.
Complete deployment-image packaging, retention, and released dependency pins
are still outstanding. The remote acceptance test below covers the implemented
publication transport, not the full feature acceptance matrix.


## Real remote publication

Build both Rust worktrees against the same APSS contract, then run:

```sh
SYN_TEST_EXPORTER_BINARY=/absolute/path/to/apss-session-exporter \
SYN_TEST_SESHMAGIC_BINARY=/absolute/path/to/seshmagic-session-store \
SYN_TEST_SESHMAGIC_MCP_BINARY=/absolute/path/to/seshmagic-session-store-mcp \
  .venv/bin/pytest packages/syn-adapters/tests/test_inventory_remote_replication.py -m integration
```

This test uses ephemeral PostgreSQL and a real SeshMagic HTTP listener. It
publishes local snapshots with invocation/native nodes, membership, lineage,
bindings, missing-body capture receipts, and gaps. The real Rust exporter queues
the APSS Python messages while the store is offline, then uploads after restart.
SeshMagic must answer run queries independently, preserve native ID spelling,
and serve pinned historical pages after its head changes.

The test restarts SeshMagic with revoked write grants and a changed read token.
HTTP and MCP stdio queries must agree on the independent replica result.
Old read credentials are rejected by both interfaces. Uploads stay pending while a newer local
snapshot remains queryable; the remote head remains at its last published
revision. The test passed with the development binaries. Released artifact pins,
production image installation, and full native-capture acceptance remain separate
delivery requirements.

## Capture delivery and acknowledgement evidence

With inventory replication enabled, set
`SYN_SESSION_INVENTORY_CAPTURE_REPLICATION_ENABLED=true` and
`SYN_SESSION_INVENTORY_CAPTURE_WRITE_TOKEN` to enable archived-envelope delivery.
SeshMagic needs an explicit `CAPTURE_WRITE_GRANTS` entry for each source/harness
pair. One token may authorize multiple listed harnesses in the same installation.
Inventory write authority does not imply capture write authority.

Live scheduling runs bounded capture enqueue and drain tasks independently from
inventory delivery. Replay only advances checkpoints. Archive metadata is stored
before local capture acknowledgement; SQL delivery jobs move eligible envelopes
into the exporter's durable outbox. Native-only captures and captures without a
known native ID are not yet eligible for this path.

`queued` proves local exporter durability, not remote acceptance. Separate fenced
receipt polls recover committed acknowledgements from the exporter. The worker
appends an immutable remote-capture evidence batch before checkpointing the poll.
A failure between append and checkpoint retries the same batch. Receipt evidence
records historical acceptance; it does not establish continuing read permission
or availability after deletion. Remote visibility and deletion reconciliation
remain unfinished.

The real capture integration test covers archive/catalog acquisition, SQL jobs,
exporter processes, independent SeshMagic/PostgreSQL, outage/restart recovery,
versioned reads, revoked writes, receipt leases, and evidence journal publication.
Unit tests inject journal and checkpoint failures and verify identical retry
batches and redacted diagnostics. Full workflow/harness acceptance remains pending.

## Pricing compatibility gap identified during integration

`HttpSessionStore.fetch_qualified_session` now supports the qualified route and
preserves native response identity and retry/error behavior. The call chain is
`import_delegates_for_phase` -> `import_phase_delegates` ->
`resolve_delegate_usage`. When `AuthoritativeCapture.qualified_session_identities`
is supplied, this chain requires an unambiguous qualified identity for each
captured native ID and calls the qualified store port. Missing or conflicting
identities remain unpriced; they never fall back to a bare-ID lookup. An absent
identity collection retains the existing `SessionStorePort.fetch_session` path.

Production capture producers do not yet populate that optional collection.
Their `agent_session_ids` still contain bare IDs without per-session harness or
source installation. A single phase may contain cross-harness children, so
inheriting the leader's harness would misattribute sessions. Wiring must carry
verified qualified identities through this boundary and retain legacy IDs as
explicitly unqualified evidence. The billing ledger and leader exclusion still
use bare IDs; their migration must preserve existing no-double-billing behavior. A 409 from the legacy route must remain unpriced rather than selecting
an arbitrary matching transcript. Qualified adapter tests alone do not prove
pricing compatibility; end-to-end delegate import and resume-ledger regressions
remain required before enabling qualified writes in a released deployment.


## Optional local body expiry

`SYN_SESSION_INVENTORY_LOCAL_BODY_RETENTION_SECONDS` enables permanent local
body expiry; unset means no automatic expiry. Age starts at first durable catalog
acquisition, not the last read or duplicate capture. The policy applies to exact
shared bytes across all local memberships. Catalog and historical inventory rows
remain discoverable. Remote replicas currently have separate retention; this
setting does not delete their bodies or already queued exporter copies.

Each live recovery signal discovers at most 100 eligible catalog rows and deletes
at most one body. SQL records pending requests; filesystem tombstones prevent
spool replay from restoring deleted bytes. Crashes after unlink but before SQL
acknowledgement safely repeat deletion. Failures remain pending and do not block
capture recovery or inventory scheduling. Preserve the tombstone files with the
archive when migrating storage. Expiry does not reclaim retained workspace spool
volumes, exporter outboxes, catalog rows, or tombstones.

Tests: `test_body_retention.py` uses real PostgreSQL and temporary archives for
bounded expiry, installation isolation, catalog preservation and interrupted
acknowledgement. `test_body_retention_scheduling.py` checks disabled defaults and
failure isolation. Cross-store deletion and user-visible expired availability
remain separate integration work.

Expiry cancels host capture-delivery jobs for the exact body across destinations.
Delivery and receipt leases reject completion after cancellation, and discovery
for a new destination excludes durable deletion requests. This stops host retry
churn; already queued exporter operations and remote copies still require
separate tombstone delivery.


Envelope expiry first asks the installed standard exporter for the APSS content
hash and commits it to the deletion request. A later tick removes bytes. Hashing
requires no remote configuration or credential. If hashing is unavailable, expiry
retains the body and retries. Capture replication queues that qualified deletion
through the exporter before advancing a destination-specific SQL checkpoint;
interrupted enqueue repeats idempotently. A destination added later discovers
retained deletion requests too. This now connects host expiry to remote deletion
transport, but physical exporter spool cleanup is still pending.

The current exporter removes deleted envelopes from its outbox spool during
bounded drain steps. Shared bytes remain until other pending qualified identities
no longer need delivery. The real remote replication test verifies physical
outbox cleanup, remote absence, delayed-upload rejection and retained catalog
metadata. Workspace source volumes are separate and are not reclaimed by this
policy yet.

## Coverage seal and bounded settlement

Coverage becomes `reconciled` or `missing` only through the host seal
(`coverage_settlement.py`, #1364). Invariant: `reconciled` only if every node
the run's evidence names (registration, child intent or context, edge,
platform session, binding, capture, transcript) is accounted for, settled and
non-conflicting. Known but unaccounted blocks it: `open` before the deadline,
`missing` or `conflicting` after.

- Expected nodes: every known node, except a transcript bound to an expected
  owner and a platform session named by the same host record as an expected
  invocation (those are accounted by their owner). The exemption lapses once
  such a node has its own receipt, lifecycle or owned binding.
- Settled: terminal process (completed, failed, cancelled, launch_failed) and
  a non-pending latest local capture receipt. Unverified child attempts,
  unresolved parentage and an unreadable child journal are unsettled.
- The seal needs the execution's terminal event (`WorkflowCompleted`,
  `WorkflowFailed`, `ExecutionCancelled`, `WorkflowInterrupted`) AND everything
  settled. A parent finishing is never enough.
- Bounded settlement: the first terminal event per run durably fixes a
  deadline `SYN_SESSION_INVENTORY_SETTLEMENT_GRACE_SECONDS` (default 1800)
  after its timestamp. Replay reads that record back, so changing the setting
  never changes an existing run's facts. Clock sweeps only record their
  observed time (also during catch-up). The live-only `process_pending()` step
  then appends one `settlement_deadline` fact per due run, compared against
  that recorded time, never the wall clock. Then unsettled processes, captures and
  child claims become explicit `*_at_seal` gaps (`missing`); unresolved
  parentage becomes `parentage_unresolved_at_seal` (`conflicting`).
- Any conflicting lifecycle, child attempt, parentage, cycle, binding or source
  claim makes coverage `conflicting`. Unsupported capture gives `unsupported`.
- A run with no host registration is `unknown` while running and `unsupported`
  with a `no_host_registration` gap once terminal. Never reconciled.
- Late evidence publishes a new revision; published revisions never change.

Unit and real-Postgres coverage:

```sh
uv run pytest -m unit packages/syn-domain/tests/contexts/agent_sessions/test_coverage_settlement.py \
  packages/syn-domain/tests/contexts/agent_sessions/test_execution_settlement_projection.py
TEST_DATABASE_URL=postgresql://... uv run pytest -m integration \
  packages/syn-adapters/tests/test_session_inventory_pipeline.py
```
