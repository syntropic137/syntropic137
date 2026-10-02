# ADR-071: Session Inventory and Discovery

- **Status**: Accepted (records the model as built under #1398; the issue itself is not closed, see Consequences)
- **Date**: 2026-10-02
- **Issue**: #1398, #1489, #1501 (item G)
- **Related**: ADR-014 (section 4, platform session linkage; section 7, resume), ADR-015, ADR-025, ADR-037, ADR-055
- **Public guide**: `apps/syn-docs/content/docs/guide/session-discovery.mdx`

## Context

ADR-014 section 4 links a session to an execution by putting `execution_id` on
`SessionStartedEvent`. That answers one question: which session did the
platform start for this phase? It cannot answer the question operators and the
learning loop actually ask: **which sessions did this execution run, and is
that list complete?**

The gap is structural. Inside a workspace, an agent starts delegates (`claude`,
`codex`) and subagents, resumes conversations, and forks them. None of those
are platform sessions, the platform did not start them, and their identities
are whatever the harness chose. A list built only from `SessionStarted` is
silently short, and a count read from a short list looks exactly like a count
read from a full one.

Three properties were required:

1. A session's identity must be qualified by where it came from, so a native
   transcript id can never be mistaken for a platform session id.
2. Every relationship (membership, parentage, binding) must carry how it is
   known, so a guess is never presented as a registration.
3. The inventory must say whether it is complete, and must be allowed to say
   "I cannot tell".

## Decision

### 1. A session is a node in one of three namespaces

`InventoryNodeRef` has `kind` in `platform`, `invocation`, `transcript`, and a
`harness` that is present only for `transcript`
(`packages/syn-domain/src/syn_domain/contexts/agent_sessions/domain/read_models/session_inventory.py:46-71`).

| Namespace | What it is |
|---|---|
| `platform` | A session the platform created and bills, one per phase run |
| `invocation` | A registered agent process launch inside a workspace |
| `transcript:<harness>` | A native session the harness recorded, keyed by the harness's own id |

A node's storage key is a SHA-256 over a versioned tuple
(`"syn-inventory-node/1"`, kind, source instance, harness, local id), so the
same local id in two namespaces or on two installations is two nodes
(`session_inventory.py:60-71`). The native id itself is never rewritten.

**A session, in this model, is a node.** "Platform session" is a narrower term,
and is the only kind ADR-014 section 4 links.

### 2. Relationships are evidence, ranked by how they are known

The inventory holds three relationship records
(`session_inventory.py:146-185`, `Membership`, `LineageEdge`, `IdentityBinding`):

- a **membership** places a node in a run, optionally a phase, attempt and segment;
- a **lineage edge** links parent to child as `spawn`, `resume` or `fork`;
- a **binding** says a platform session or invocation *is* a native
  transcript, so one piece of work is not counted twice.

Each carries an `EvidenceClass`: `registered` > `corroborated` > `candidate`,
with `conflicting` ranked lowest (`domain/services/inventory_resolution.py:26-31`)
and every record lists the `EvidenceReference`s it rests on. When several
claims agree, the strongest class is kept; when they disagree, the result is
`conflicting`, not a choice.

### 3. Sessions are discovered from evidence, never by launching or fetching

Evidence enters from two directions:

- **Host evidence from existing events.** `HostSessionEvidenceProjector`
  projects `SessionStarted`, `SessionInvocationRecorded`,
  `SessionInvocationBindingConflicted`, the execution's terminal events,
  `SessionCompleted` and the reconciliation sweep clock
  (`slices/reconcile_session_inventory/HostSessionEvidenceProjector.py:105-131`).
  It "projects durable facts only; never launches work or fetches transcripts"
  (`:67`). A `SessionStarted` is a platform node; it does not prove a native
  invocation, capture completeness, or a native parent id (`:69-70`).
- **Capture evidence from the workspace.** Native transcripts are captured into
  the host archive and recorded as `CaptureReceipt`s, each with a
  `BodyAvailability` of `present`, `pending`, `missing`, `expired` or
  `unknown`, a per-producer `receipt_sequence`, and for a present body the
  SHA-256 of the archived bytes (`session_inventory.py:81-87`, `:121-139`). Reading a
  harness's transcript format is the harness adapter's job in
  agentic-workspace, reached through ports in
  `contexts/agent_sessions/ports/`, never reimplemented here.

### 4. Aggregation per execution is a pure, deterministic resolution

`resolve_relationships` takes the complete acquired evidence for a run and
returns the resolved inventory: nodes, memberships, edges, bindings, gaps and
coverage. It does no I/O and no billing
(`domain/services/session_relationship_resolver.py:1-4`, `:134`). A node exists
in the result if any claim names it (`_nodes`, `:63-93`); historical transcript
nodes do not require a fabricated invocation.

Resolution is published as an immutable **inventory revision** (snapshot).
Late evidence publishes a new revision; a published one never changes, and
paging always reads one pinned revision.

Publication is a long-running process and follows ADR-025:
`InventoryReconciliationProcessManager` projects to-do state on replay and
dispatches leased work only when live (`slices/reconcile_session_inventory/projection.py:1`, `:48`).
`InventoryReconciliationAggregate` owns the transitions `pending -> publishing
-> completed`, or `failed` from either. A terminal reconciliation cannot be
reset, completion requires publication, a replayed step may not change its
result, and an idempotency key cannot be reused for different work
(`domain/aggregate_inventory_reconciliation/InventoryReconciliationAggregate.py:58-99`).

### 5. Coverage says whether the list is complete, and may say it cannot tell

Coverage is one of `unknown`, `open`, `reconciled`, `missing`, `unsupported`,
`conflicting` (`session_inventory.py:89-95`). The rule is in
`domain/services/coverage_settlement.py:1-40` and is pure, recomputed on every
reconstruction:

- `reconciled` only when every node the evidence names is accounted for,
  settled and non-conflicting, and the execution is terminal. A parent
  finishing is never enough on its own.
- Settlement is bounded. A terminal execution fixes one deadline
  `settlement_grace` after the terminal event's own timestamp (setting
  `settlement_grace_seconds`, default 1800,
  `packages/syn-shared/src/syn_shared/settings/session_inventory.py:34-39`).
  Deadlines are released against the latest *recorded* clock event, never the
  wall clock, so replay reproduces them (`HostSessionEvidenceProjector.py:72-78`).
  After the deadline, unsettled work becomes explicit gaps and coverage is
  `missing`; unresolved parentage is `conflicting`.
- Any conflicting lifecycle, parentage, cycle, binding or source claim is
  `conflicting` regardless of the deadline.
- A run with no host registration is `unknown` while running and
  `unsupported` once terminal: legacy and uninstrumented runs are classified,
  never reconciled.

The API reduces this to one verdict, `summary.complete`: coverage
`reconciled`, the revision `current`, and no later evidence pending
(`apps/syn-api/src/syn_api/routes/executions/inventory_summary.py:101-104`).
Every client prints the server's verdict rather than recomputing it.

### 6. A superseded transcript revision's issues do not count (#1489)

"Revision" has a second meaning here and the two must not be confused. An
**inventory revision** is a published snapshot (section 4). A **transcript
revision** is one capture of a native transcript. A live transcript is
captured repeatedly while it grows, so an early capture taken between an Agent
call and its result reports `unresolved_spawn`, which the next capture
resolves. Left alone, that stale issue holds coverage open or turns it
`missing` for a child that is in fact resolved.

The rule (`domain/services/superseded_revisions.py:1-55`), applied before
resolution (`session_relationship_resolver.py:136`):

- A later **local** receipt whose availability is `present` supersedes the
  acquisition-gap issues extracted from earlier receipts of the same transcript.
- "Later" is comparable only inside one producer's stream: the pair
  (`producer_id`, node key), by `receipt_sequence`.
- A later receipt without content (`pending`, `missing`, `expired`) supersedes
  nothing. Remote receipts supersede nothing.
- An issue is linked to its revision by the full `EvidenceReference`, so only
  that revision's issues are dropped.

Only the issues are dropped. The earlier receipts themselves stay in the
record: receipts are history and never change.

## Rejected alternatives

- **Extend `SessionStartedEvent` with child and native ids.** The platform does
  not start those sessions and learns of them late or not at all; putting them
  on the platform's own event would make the event claim what the platform
  never observed.
- **One flat session id space.** Native ids are chosen by the harness and are
  not unique across harnesses or installations. Qualification is the only
  thing that makes "same session" decidable.
- **Report a count without a coverage state.** A short list is
  indistinguishable from a full one. `unknown` and `unsupported` exist so the
  system can decline to claim completeness.
- **Let any later receipt supersede earlier issues.** A later `pending` or
  `expired` receipt carries no content, so it cannot show the earlier issue was
  resolved. Superseding on it would hide real gaps.

## Consequences

### Positive

- "Which sessions did this run, and is that all of them?" has an answer, and
  the answer can be "not known yet" or "cannot be known".
- Inventory revisions are immutable, so a saved snapshot is reproducible.
- Resolution is pure, so it is testable without infrastructure and replayable.

### Negative

- Two meanings of "revision" in one context. This ADR and the public guide
  both qualify the word; code readers must too.
- Completeness waits for settlement: up to the grace period after an
  execution ends, a finished run reads `open`.
- #1398 is not closed. The acceptance audit in
  [docs/testing/issue-1398-checkpoint.md](../testing/issue-1398-checkpoint.md)
  lists the criteria still requiring work. This ADR records the model as
  built, not a claim that every criterion is met.

### Testing

- [docs/testing/issue-1398-checkpoint.md](../testing/issue-1398-checkpoint.md):
  acceptance criteria and their evidence.
- [docs/testing/session-inventory-recovery.md](../testing/session-inventory-recovery.md):
  the Docker recovery test for captures from a workspace killed before
  finalization.
