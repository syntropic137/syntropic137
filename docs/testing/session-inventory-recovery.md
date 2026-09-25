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
metadata. Workspace source volumes are reclaimed by the spool release owner
described below.

## Transcript authorization, deletion and retention (rows 10 and 11)

Scope: Syntropic137 has no per-user principal (ADR-059). The boundary is the
gateway-authenticated installation plus current execution visibility. Raw-token
scope differences are proven on the SeshMagic side.

Whole-object policy. Revocation and deletion are keyed by the archived byte
SHA-256, so a decision taken through one run applies to every run whose
membership shares those bytes. The exact revision must be catalogued for the
addressed, currently visible run; otherwise the API answers `not_captured` (read)
or 404 (write) without size, format or bytes. Identifiers are opaque lookup keys,
never paths or fetch URLs.

Routes (all `Cache-Control: no-store`, fixed error strings):

- `GET /executions/{id}/session-transcripts/{archive_hash}`: exact bytes or an
  explicit `not_captured`, `missing`, `expired`, `deleted` or `too_large` status.
  Revoked objects answer 403.
- `POST .../{archive_hash}/revocation`: withhold reads; bytes are retained.
- `POST .../{archive_hash}/deletion` (`reason`: `deletion` or `retraction`):
  idempotent durable tombstone, 202. The body is withheld from that commit on,
  delivery jobs are cancelled, and a later tick erases bytes.
- `GET .../{archive_hash}/deletion`: local erasure and per-destination replica
  propagation state.

Redaction. Bodies can contain whatever the agent saw. The API serves exactly the
archived bytes (`redaction: "source"`): only redaction the capturing source
applied before archival. The server never rewrites or slices bytes. Error bodies
and background-task logs carry fixed text or an exception class name, never an
exception message, path, token or payload.

Hash naming. `archive_sha256`, `archived_byte_hash` and `archived_bytes_sha256`
are SHA-256 of archived bytes. `source_content_hash` is the APSS original-content
hash (`sha256:` prefix) used by replicas. Capture pages add `capture_hashes[i]`
naming what `items[i].transcript_revision` holds, because local and remote
receipts store different representations in that field.

Anti-resurrection. Once tombstoned, bytes cannot return through archive re-put
(filesystem marker), spool replay, capture retry (claim excludes tombstoned
objects), a new destination (discovery excludes them) or a replica retry (one
checkpointed delete per capture and destination). Catalog rows, inventory
revisions and body overrides keep the session discoverable with `expired`,
`deleted` or `withheld`, including replica receipts matched by content hash.

Quotas (all disabled by default, ADR-004 settings forwarded through compose):

- `SYN_SESSION_INVENTORY_LOCAL_BODY_MAX_BYTES`: distinct archived objects are
  counted once; the oldest are tombstoned as `retention_quota` until the newest
  fit. Owner deletions run whether or not any quota is set.
- `SYN_SESSION_INVENTORY_SPOOL_RETENTION_SECONDS` and
  `SYN_SESSION_INVENTORY_SPOOL_MAX_BYTES`: a spool past its age, or the oldest
  settled spools past the byte quota, expire. A `capture_spool_expired` gap is
  journaled before the volume is removed. Live sessions are never evicted by the
  byte quota.
- `SYN_SESSION_INVENTORY_SPOOL_SETTLE_GRACE_SECONDS` (default one day): see below.

Spool release. A workspace spool volume is removed only after durable local
archive acknowledgement or recorded expiry. `archived` release requires a
complete transcript and child traversal whose lease began after the session
settled (`SessionCompleted`), or after the settle grace for sessions that never
reported completion, with no other container attached when the volume was
opened. Docker refuses to remove an attached volume; an interrupted archived
release reopens the spool for capture. `release_reason` is committed before
removal and `released_at` after, so a crash repeats an idempotent removal. The
cleanup owner runs only from the live inventory tick, never from replay.

Known limits: sessions completed before this change are not settled
retroactively (the projection version is unchanged, to avoid a full replay);
they release through the settle grace instead. The archive byte quota scans the
installation's catalog each tick, bounded by the catalog index.

Tests: `test_transcript_authz_postgres.py` (API matrix: shared membership,
malformed/traversal/NUL IDs, foreign run and installation, revoked, deleted,
expired, missing, too large, resurrection, planted secrets),
`test_transcript_deletion_postgres.py` (whole-object tombstones, replica
propagation, quota), `test_spool_release_postgres.py` (settlement, exclusivity,
expiry gaps, byte quota), `test_docker_spool_release.py` (real Docker in-use
refusal), plus unit tests for the recovery worker and projector.
