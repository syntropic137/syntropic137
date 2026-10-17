# ADR-076: Feedback Ticketing

- **Status**: Proposed
- **Date**: 2026-10-17
- **Issue**: #1970 (feedback ticketing server), #1628 (tell a reporter their fix has shipped)
- **Plan**: `docs/plans/20261017_feedback-ticketing-server.md`, in PR #2010 (not yet merged). This ADR records the decisions; the plan has the build sequence.
- **Supersedes in part**: [ADR-016](ADR-016-ui-feedback-module.md) (UI Feedback Module): its storage and lifecycle, not its capture UI
- **Related**: ADR-020 (bounded-context convention), ADR-060 (in-memory adapters refuse production), ADR-062 (cross-context public API)

## Context

ADR-016 stores each feedback item as a row in lib/ui-feedback's own table, with its
text, its media and a status someone edits by hand. Three things that model cannot
do are now needed:

1. **Many deployments, one inbox.** Self-hosted deployments should be able to send
   feedback to a central deployment, and an untrusted network path needs abuse controls
   and provenance that a local table never had.
2. **Agents read feedback.** The orchestrating skill reads open feedback and acts on it.
   Any free text a reporter wrote is therefore a prompt-injection channel, and it must be
   possible to keep that text from an agent until the owner has looked at it.
3. **"Fixed" must mean something a reporter can check (#1628).** A merged PR is not a
   fix in the reporter's deployment. Betas create no GitHub release, so "it shipped"
   cannot always mean "a release contains it".

## Decision

### 1. A new bounded context, `feedback`

`packages/syn-domain/src/syn_domain/contexts/feedback/` is its own bounded context
because its words collide with orchestration's. **Quarantine** there is a git ref;
here it is a ticket whose text no agent may read. **Eval** is an orchestration
aggregate; here the classifier suite is a **Screening Benchmark**. **Shipped** is
reserved there. The vocabulary is in
[feedback-ubiquitous-language.md](../architecture/feedback-ubiquitous-language.md).

### 2. The Ticket aggregate holds ids and hashes, never reporter text

A **Ticket** is built from one or more submissions. Its events carry the
`submission_id` and the sha256 `content_hash` of the Screened Text, never the text
itself. The text stays in a purgeable intake log outside the event store. The event
store cannot be erased, so text there could never be deleted. Text there would also
reach every projection, and through them every agent.

The Ticket's events are `TicketOpened`, `TicketReportAdded`, `TicketReportDetached`,
`TicketReleasedFromQuarantine`, `TicketReprioritised`, `TicketLinkedToIssue`,
`TicketLinkedToExecution`, `TicketPullRequestLinked`, `TicketPullRequestStateChanged`,
`TicketFixObserved`, `TicketFixReleased`, `TicketResolved`, `TicketClosed` and
`TicketReopened`. The free-text fields that remain (`by`, `reason`) are written by the
owner, are length-capped, and never hold reporter text.

The aggregate's rules:

- **Retries are no-ops, not errors.** A second `OpenTicket` with the same ticket id and
  submission is a no-op success. A submission that is already a member is a no-op, so
  the reporter count can never rise twice for one submission. A PR that is already
  linked is a no-op. A PR is keyed by repository id and number, never by repository
  name, so linking or observing it after a rename reaches the same PR. The Screener retries after a crash, and none of these may count
  twice.
- **Quarantine is contagious in one direction only.** A quarantined submission never
  joins a clean ticket. A quarantined ticket cannot be linked to an issue, an execution
  or a pull request until the owner releases it.
- **PR observations are ordered.** An observation older than the last one recorded is
  ignored, and `merged` is terminal.
- **Status is derived, never stored**, in this order: `quarantined`, `closed`, `resolved`,
  `in_progress` (any linked PR open), `fix_merged` (any linked PR merged), `open`. An open
  PR outranks a merged one, so a second fix still in flight, or a PR closed and then
  reopened, reads as in progress.

### 3. Resolution Policy (proposed default: decision D7, awaiting the owner)

A ticket resolves when **(a)** a published release contains the fix, **or (b)** every
*signed* source with a report on the ticket has observed the fix in its own deployment.
Anonymous reports, and sources that never report again, resolve through (a). (b) exists
because betas create no release. A ticket with no signed reporter never resolves through
(b): an empty set is not "everyone observed it".

`TicketResolved` is emitted by the aggregate in the same command whose event made the
policy true, and it names the version. Per source, the latest observation wins, so an
older observation that arrives late cannot un-resolve a ticket. Reopening a resolved
ticket (a regression) discards the fix evidence, because the fix did not hold: its
merged PRs become spent fixes, and its observations and release stop counting. The
per-source observation watermarks and the release tags survive the reopen, so a
retry of that same evidence is a no-op and cannot resolve the regression again. Only
a newly merged PR makes a fix observable or releasable again.

**This rule is a proposal.** It is implemented as the default so the domain can be
built and tested. If the owner chooses differently, only `ResolutionPolicy` and its
tests change.

### 4. Pure domain services, not aggregates

- **Screened Text**: deterministic normalisation (NFC; strip C0/C1 controls,
  every Unicode format character (Cf), which covers zero-width characters and all
  twelve bidi controls; collapse whitespace; redact secret shapes; cap at
  4,000 characters). It is the only text an agent may read. Redaction is defence in
  depth and **is not a PII control**.
- **Screening Policy**: maps a classifier's verdict and confidence to open, quarantine
  or drop. Doubt always lands in quarantine.
- **Near Duplicate Matcher**: word-shingle Jaccard similarity, compared only within a
  match bucket (the same route, or the same type when there is no route).

### 5. Ports owned by feedback

`ScreeningPort`, `IntakeLogPort`, `NonceLedgerPort`, `RateBucketsPort` and `ForgeReadsPort` are defined
in `feedback/ports/`. The plan names four of them without the suffix (`IntakeLog`, `NonceLedger`, `RateBuckets`, `ForgeReads`); they carry `Port` here because ADR-019's naming rule is enforced by `vsa validate`. `NonceLedgerPort` is feedback's own port even though github's public
`DedupPort` has the same shape. This is a design judgment, not an ADR-062 requirement:
rejecting a replayed request and deduplicating a GitHub event change for different
reasons. `RedisDedupAdapter` satisfies it structurally, and
`syn_adapters.port_conformance` checks that pairing. The other four ports get their
adapters in later PRs of the plan.

### 6. ADR-016 is superseded in part

ADR-016's capture UI (the dialog, screenshots, voice notes) stands. Its storage, status
lifecycle and CRUD routes are superseded by this context and are removed once every
consumer has migrated (plan PRs 8, 9 and 13).

## Consequences

- **Positive:** a quarantined injection string cannot reach an agent through any
  projection, because no projection ever holds text. Resolution is a checkable fact per
  reporter. A context boundary lets "quarantine" mean two things without ambiguity.
- **Negative:** reading a ticket's text needs a join to the intake log, and a purged log
  leaves a ticket with no readable text. That is intended.
- **Negative:** the platform clock this context will wake on
  (`InventoryReconciliationSweep`) is a cross-context name used by string. Whether it
  becomes a neutral platform tick is an open question, recorded as **Unclear** in the
  vocabulary.
- **Not yet built:** the Source aggregate and signing (plan PR 2), Intake (PR 3), the
  Relay (PR 4) and every route. This ADR's first PR is domain-only.
