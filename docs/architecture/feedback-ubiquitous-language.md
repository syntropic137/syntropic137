# Ubiquitous Language: feedback

## Purpose

The vocabulary of the `feedback` bounded context: tickets built from screened
user feedback ([ADR-076](../adrs/ADR-076-feedback-ticketing.md)). These words have
exactly these meanings in code, in the API, in the CLI and in conversation. Where a
term here disagrees with any other document, this one is canonical.

For event-sourcing patterns (Event, Aggregate, Projection) see `es-glossary.md`.

Several words here also exist in orchestration with a different meaning. That is
why feedback is a context of its own. Each collision is named under the term.

## Terms

### Submission

One raw report as Intake received it. It lives in the intake log, which is
purgeable, and it is **not** a domain object: no event ever carries its text.
Events name it by `submission_id` and by the `content_hash` of its Screened Text.

### Receipt

What Intake's 202 returns: a `submission_id`. A receipt is **not** a ticket. A
submission may become a ticket, join one, or be dropped.

### Relay

A deployment's server-side sender. It owns the source key, stamps build provenance
(version and commit come from the server, never the browser) and keeps the outbox.

### Intake

The public entry point that throttles, verifies, caps and appends. It never
decides what a submission means.

### Lane

How a submission arrived: *signed* (from an enrolled Source), *anonymous*
(Turnstile), or *legacy* (imported from lib/ui-feedback). On the anonymous lane,
`source_id` is absent.

### Source

An enrolled deployment holding a signing key (`SourceAggregate`, one per
`source_instance_id`). It is **not** a GitHub source and **not** a
session-inventory source. Its status is `active`, `throttled` or `revoked`
(`SourceStatus`); **revoked** is terminal and outranks everything below.

- **Enrol** (`SourceEnrolled`): the source's first key and its daily quota.
  Enrolling again with the same key is a no-op; with a different key it is refused.
- **Verification key:** the public half the event store holds. Under Ed25519 it
  is the public key; if D2 picks HMAC it is the secret's hash. The **signing
  key** never leaves the source's Relay and never enters this context.
- **Key id:** names one key. A source never reuses a key id.
- **Rotate** (`SourceKeyRotated`): a new current key. The replaced key is
  **retired** at the rotation time and keeps verifying for the **rotation
  overlap**, a verifier setting rather than a recorded fact.
- **Throttle / Lift** (`SourceThrottled`, `SourceThrottleLifted`): SourceGuard
  throttles; the owner lifts. A throttled source still verifies; Intake rejects
  it at the quota step.
- **Revoke** (`SourceRevoked`): no key of the source verifies again, including a
  retired key still inside its overlap.

### Signed Request / Canonical String / Signature Window

A **Signed Request** carries `X-Syn-Source`, `X-Syn-Key-Id`, `X-Syn-Timestamp`,
`X-Syn-Nonce` and `X-Syn-Signature`. The **Canonical String** is what a source
signs: `method \n path \n ts \n nonce \n sha256(body)`. The **Signature Window**
is ±300 s around the verifier's clock, inclusive. A **Verification** is the
verdict: `verified`, or one of `revoked`, `stale_timestamp`, `unknown_key`,
`key_retired`, `bad_signature`. The **Signature Algorithm** is D2's seam
(`SignatureAlgorithm`); Ed25519 is the one built. The `feedback_sources` read
model holds each source's status, quota and keys, and is what Intake verifies
against.

### Provenance

`key_id`, surface, the server-stamped version and commit, and the route. A
submission with no key is `anonymous`.

### Screening / Screening Verdict

The classifier pass over Screened Text (`ScreeningPort`). The verdict is `clean`,
`quarantine` or `spam`, plus a type, a priority and a confidence. The classifier
classifies; the **Screening Policy** decides what happens: open, quarantine or drop.
Doubt always lands in quarantine.

### Disposition

What the Screener decided for one submission: `open`, `report`, `exact_duplicate`,
`quarantine`, `spam` or `failed`. It is persisted before any command is sent, so a
retry never decides twice.

### Screened Text

The normalised, capped, secret-shape-redacted text (`ScreenedText`). It is the only
text an agent may read. It is **not** a PII guarantee: redaction is defence in depth.

### Ticket / Ticket Number (`FB-<n>`)

The aggregate built from one or more submissions (`TicketAggregate`). The number is
unique within the hosting deployment and never reused. Gaps are allowed.

### Quarantine (feedback)

A ticket whose text no agent and no public surface may see until the owner releases
it. A quarantined submission never joins a clean ticket. A quarantined ticket cannot
be linked to an issue, an execution or a pull request.

It is **not** orchestration's Quarantine Ref, which is a git ref
(`orchestration-ubiquitous-language.md`, "Quarantine Ref").

### Report / Reporter Count

A submission that is a member of a ticket. Membership is unique per submission:
adding the same submission twice leaves the count unchanged. The submission that
opened the ticket is its first report.

### Exact Duplicate

The same content hash from the same scope inside the dedup window. It is **not** a
Report and does not raise the count.

### Near Duplicate

A submission whose similarity to a ticket's text (`NearDuplicateMatcher`,
word-shingle Jaccard) is above the threshold, compared only within a **Match
Bucket**: the same route, or the same type when there is no route. A near duplicate
**is** a Report, and its similarity is recorded.

### Recurrence

A submission matching a closed or resolved ticket. It opens a new ticket that names
the old one in `recurrence_of`. A closed or resolved ticket never gains reports.

### Detach

The owner's correction of an over-merge: a submission is taken off a ticket and is
reopened as its own ticket.

### Fix Merged / Fix Observed / Fix Released / Resolved

The #1628 facts.

- **Fix Merged**: a linked pull request merged. As a status, `fix_merged` holds only
  while no linked PR is still open; an open PR reads as `in_progress`.
- **Fix Observed**: per source. One deployment reports whether its running build
  contains the fix. Per source, the latest observation wins.
- **Fix Released**: a published release contains the fix.
- **Resolved**: the **Resolution Policy** is true. Either the fix is released, or
  every *signed* reporter has observed it. A resolution names a version. The policy
  is a proposed default awaiting the owner (decision D7 in the plan, PR #2010).
- **Spent Fix**: a merged PR on a ticket that was then reopened. The fix did not
  hold, so neither it nor the observations and release that resolved the ticket count
  again; replaying that evidence is a no-op. Only a newly merged PR can resolve it.
- A linked pull request is identified by its **repository id** and number. The
  repository name is only how it was displayed, so a rename is the same PR.

### Digest / Quarantine Alert

A batched summary for the owner, and a spike notice. Neither ever holds quarantined
text.

### Screening Benchmark

The grouped train/validation/holdout suite used to choose a screener.

## Words not used here

- **Shipped**: orchestration's word, reserved for agent-authored work. Say Fix
  Released or Resolved.
- **Eval**: orchestration's aggregate. Say Screening Benchmark.
- **Feedback item**: the legacy lib/ui-feedback term. Say Ticket or Submission.
- **low / medium / high / critical**: say P0 to P3. Legacy values map critical to P0,
  high to P1, medium to P2 and low to P3.
- **Pause**: there is none here either.

## Unclear

**Unclear:** the platform clock this context wakes on is named
`InventoryReconciliationSweep`. That is a cross-context name used by string,
following orchestration's precedent. Whether it becomes a neutral platform tick is
#2012.
