# Plan: a `syn137/verified` commit status per reviewed head (#2057, with #2081)

**Status.** Proposed, 2026-10-23. Docs only: no code changes in this PR. Every
citation to `main` was read at `origin/main` while writing it.

**Owner decisions needed** are collected in [section 12](#12-open-questions-for-the-owner).

---

## 1. The problem, measured

`finalize_pr` marks a PR ready only on a certified verdict. Nothing enforces
that a merged head was the head certified. #2057 measured 200 merged PRs
(2026-10-01 to 10-21) that had a workflow verify report:

| Class | PRs |
|---|---|
| certified on the head that merged | 86 |
| certified on an older head; later commits only merged main in | 22 |
| certified on an older head; later commits only add or remove `.mutations/` | 11 |
| certified on an older head; later commits change code | 33 |
| blocked or no verdict, then merged | 48 |

Of the 48, 11 have no recorded clearance at all. The clearances that exist
live only in PR comment text. The full table and method are in the #2057
issue comment of 2026-10-22.

Two facts make it fixable:

- **The verdict is already a domain fact.** A reviewing Phase reports
  `review_verdict` in its TASK_RESULT. It lands on `AgentExecutionCompleted`
  as `reported_review_verdict` (`domain/events/AgentExecutionCompletedEvent.py:67`).
  `ReviewRecord.report` then folds it into the aggregate
  (`WorkflowExecutionAggregate.py`, `on_agent_execution_completed`).
- **The reviewed commit is NOT a domain fact yet.** Every Phase's provisioning
  records its Starting Checkout, read back and verified against the pin (#967):
  `WorkspaceProvisionedForPhase.checked_out_commits`. But a verify Phase today
  is provisioned at the run's pin, and the agent then checks out the
  implementation SHA it read from an artifact. That is
  `workflows/sdlc/implement-v4-precheck/phases/verify.md`, "First: check out
  the code you are verifying", and `reverify-pr`'s `prepare` resolves the PR
  head the same way. So the commit judged is chosen by an agent, and the
  platform has not verified it.

So three things are missing:
- a platform-resolved, read-back **review target** (slice S0);
- a record joining verdict and target per commit;
- something that tells GitHub.

Until S0 ships, no review counts toward a Head Certification.

## 2. Outcome

- Every head a platform review judged carries the commit status
  `syn137/verified`: `success` when the latest review of that head certified
  it (or an override or carry-forward stands for it), `failure` when the
  latest review blocked it.
- A new push lands on a new SHA, which has no status. So "certified on an
  older head" can no longer pass silently: the merge sees no status.
- Overrides are recorded facts with an actor, a reason and an evidence link,
  never only a comment.
- Shipped dark behind a flag. Making the status a required check is a
  separate owner decision, taken on measured data (section 9).

## 3. Vocabulary (orchestration context)

Added to `docs/architecture/orchestration-ubiquitous-language.md` by slice S1
and S2:

- **Platform Review Target (workflow capability).** A Phase-level YAML field,
  `review_target: platform`, frozen with the definition at start. It is an
  opt-in promise that the Phase's prompt does no checkout of its own. Today's
  arms (implement-v3, v4-precheck and its sonnet-fix arm, reverify-pr, the eval
  workflows) declare `requires_verdict` but check out the implementation SHA
  themselves, so they never declare it and are excluded. `just check-workflows`
  refuses the field on a phase whose prompt contains a `git checkout` or
  `git switch` step.
- **Reviewing Phase.** A Phase that declares both `requires_verdict` and
  `review_target: platform` in its frozen definition (the workflow as pinned
  at start). Only its Review Verdict can move a Head Certification. A Phase
  that reports a verdict without both, such as an implement Phase or an older
  verify arm, is ignored. So an author cannot certify its own change, and a
  provisioning checkout is never mistaken for a reviewed head.
- **Review Target.** The commit, per repository, that the platform resolves
  for a Reviewing Phase before provisioning it. That is the branch head this
  Execution's own earlier Phases pushed (Own Push), or, for a PR-targeted run,
  the PR's head as the forge reports it. The platform checks it out, reads it
  back, and persists it as its own fact (`ReviewTargetResolved`), separate
  from the Starting Checkout. The agent never chooses it.
- **Reviewed Head.** A Review Target whose Reviewing Phase reported a verdict.
- **Head Certification.** The platform's standing judgement of one commit in
  one repository. It is folded from every Review Verdict about that Reviewed
  Head, plus Certification Overrides and Carried Certifications. Its state is
  `certified`, `blocked` or `unreviewed`. It has its own stream per
  `repository@sha`.
- **Certification Override.** A person's recorded decision that a head is
  certified, despite a blocked or absent verdict. It carries the actor, the
  reason and an evidence link, such as the integration run that settled
  Docker-only evidence.
- **Carried Certification.** A certification that a later head inherits from
  an earlier certified head (section 6).
- **Base Merge.** A commit with two parents, the second on the base branch.
  Its tree equals the tree of a clean merge of the same two parents, computed
  by the platform. Any conflict resolution or extra edit means it is not one.
- **Mutation-only Commit.** A commit with one parent whose every changed path
  is under `.mutations/`.
- **Verified Status.** The GitHub commit status, context `syn137/verified`,
  that publishes a Head Certification. It is a projection of a Lane 1 fact
  onto the forge, never a source of truth: the aggregate is the truth.

Not used: **Approval** (a GitHub review is an approval; this is not a review),
and **Verdict** alone (an eval Verdict is `PASS`/`FAIL`/`ERROR` about a Run;
see that entry).

## 4. Ownership and events

### 4.1 WorkflowExecution (existing aggregate) gains one event

`ReviewVerdictRecorded`, emitted by the aggregate's own command handler
(never by an event handler) when a **Reviewing Phase** completes with a verdict
and a Review Target. It carries:

| Field | Source |
|---|---|
| `execution_id`, `phase_id`, `workflow_id` | the aggregate |
| `verdict` | `ReviewRecord.of(phase_id)` |
| `reviewed_heads: list[SourceCommit]` | that Phase's `ReviewTargetResolved` (S0), checked equal to the commits its `WorkspaceProvisionedForPhase.checked_out_commits` read back; a mismatch emits no verdict |
| `verifier_model` | `AgentExecutionCompleted.agent_model` for that Phase |
| `pull_requests: list[(repository, number)]` | `ObservedHead.open_pr_number` from that Phase's `ArtifactsCollectedForPhase`, when observed |

Why a new event rather than letting a subscriber join three: the aggregate
already holds all three facts, and joining them is a rule. Rules belong in
the aggregate, not in a ProcessManager. The aggregate keeps only the first
provisioning's checkout today (`_starting_checkout`), so S1 adds a per-Phase
map of checkouts.

A Reviewing Phase with no Review Target (one provisioned before S0, or with no
repo checkout) emits no event. **No historical backfill.** Streams recorded
before S1 contain no `ReviewVerdictRecorded`, and replay never creates one:
past reviews were never platform-targeted, so their SHA is not a fact.

### 4.2 HeadCertification (new aggregate, orchestration)

`domain/aggregate_head_certification/HeadCertificationAggregate.py`. One
stream per `repository@sha`, created with `ExpectedVersion.NoStream`
(stream-per-unique-value). It decides; nothing else does.

| Command | Event | Rule |
|---|---|---|
| `RecordReviewOfHead` | `HeadReviewed` | Idempotent on `(execution_id, phase_id)`: a duplicate records nothing. |
| `OverrideCertification` | `CertificationOverridden` | Needs actor, reason and evidence link. Refused for an empty reason. |
| `CarryCertificationForward` | `CertificationCarried` | Idempotent on `(source_sha, source_version)`. Refused when this head already has an explicit decision (a review or an override), and refused unless the typed facts in section 6 qualify. |
| `RevokeCarriedCertification` | `CarriedCertificationRevoked` | Sent when the source head's state leaves `certified` at a later version. |
| `RecordEvidenceForHead` (S8) | `HeadEvidenceRecorded` | Idempotent on `(execution_id, gate_id, step)`. |

**Every save that changes the derived state also emits
`CertificationStateChanged`** in the same save: `from_state`, `to_state`,
`version`, `cause` (the event that moved it). It is the only event the
publisher reads, so no transition can be missed, including revocation and an
evidence failure arriving after a certification. State is derived by one
table (section 10); there is no other rule.

**Who may override.** `OverrideCertification` is accepted only from an
authenticated operator identity holding an explicit override permission. A
workspace token or an internal request without a person is refused. Today
`workspace_ingress` passes internal requests without a person, so S5 adds the
check at the route and records the authenticated identity as the actor, not a
field the caller supplies.

## 5. ProcessManagers (Processor To-Do List, ADR-025)

Both live in `slices/publish_verified_status/` and follow
`QuarantineNoticeProcessManager`: `handle_event` writes to-do records and is
pure and replay-safe, and `process_pending` does the work, live only.

**`HeadReviewIntakeProcessManager`.**
- Subscribes to `ReviewVerdictRecorded`, and to the recovery clock
  (`InventoryReconciliationSweep`). The coordinator skips `process_pending`
  during catch-up, so without a clock, a to-do written during replay would
  wait for the next review.
- To-do: one per `(execution_id, phase_id, repository, sha)`, in the
  persistent projection store, written as a replay-safe upsert.
- Process: dispatch `RecordReviewOfHead` to that head's stream. Mark the to-do
  done only after the aggregate save succeeds; the aggregate's dedup makes a
  retry safe.
- No forge I/O.

**`VerifiedStatusProcessManager`.**
- Subscribes to `CertificationStateChanged` only, plus the recovery clock
  (`InventoryReconciliationSweep`) for carry-forward checks and retries.
- To-do: one per `(repository, sha, context)`, holding the desired state and
  the aggregate version it came from.
- Process: post the status when `posted_version < desired_version`. The
  mapping, so a success once posted is always replaced when it stops being
  true:

  | state | status | description |
  |---|---|---|
  | `certified` | `success` | how: reviewed by `<workflow>`, overridden by `<actor>`, or carried from `<sha>` |
  | `blocked` | `failure` | the cause: blocked review, or a named evidence step failed |
  | `unreviewed`, never published | nothing posted | |
  | `unreviewed` after a publish (revoked carry, evidence unresolved) | `pending` | "not verified at this head: <cause>" |

  `pending` rather than `failure` for an unresolved head: nothing has been
  found wrong, but it is not verified, and a required `pending` blocks merge.

**Idempotency and ordering, keyed on `(repository, sha, context)`.** A GitHub
status is append-only per SHA, and the latest one to arrive with a given
context wins. Arrival order is not version order, so a stale `success` from
one worker could land after a newer `failure`. Therefore:

- Publishing is serialized per key with a durable lease, the same Postgres
  row-lock pattern the run queue uses, never an in-memory lock.
- Under the lease, the publisher re-reads the aggregate's current version and
  state, posts that, and records `posted_version`.
- An uncertain write (a timeout or a 5xx) is reconciled on the next pass. The
  publisher reads `GET /repos/{o}/{r}/commits/{sha}/statuses`, compares, and
  re-posts if they differ.

**Replay safety.**
- `handle_event` never calls the forge.
- History cannot produce statuses. Nothing before S1 emits
  `ReviewVerdictRecorded` (section 4.1).
- The publisher also has a durable **publication epoch**, an event
  `VerifiedStatusPublishingEnabled` recorded once when an operator enables
  it. A to-do whose source event precedes that epoch is marked `historical`
  and posts nothing. That decision is stored on the to-do, so a restart
  cannot reclassify it.
- Restarts resume from the checkpoint as usual.

## 6. Carry-forward

The PR head moves past a certified SHA. There is no stored "PR head moved"
event (`github/domain/events/` holds only installation and trigger events), so
the clock tick wakes the check, the same way the Quarantine Notice is woken.

For each certified head S with an open PR, `process_pending` runs a host-side
handler (no logic, only reads) that:

1. Asks the forge for the PR's head S′. It stops if S′ equals S.
2. Builds typed `CarryFacts`:
   - `source=(S, version)`, read from S's stream, which must be `certified` at
     that version;
   - the **first-parent path** from S′ back to S (`git rev-list --first-parent
     S..S′`), and whether it reaches S. Commits that a base merge brings in
     from main are not on this path and are not judged one by one: main's own
     ordinary code commits are expected there;
   - for each two-parent commit on the path: whether its second parent is an
     ancestor of the base branch's head (`git merge-base --is-ancestor`), and,
     as a separate fact, whether its tree equals a clean merge of its two
     parents computed in a scratch clone (`git merge-tree --write-tree`);
   - for each one-parent commit on the path, its changed paths;
   - the base branch's required checks: the union of the paginated rules API
     and classic protection (a 404 from classic protection means none is
     configured), **minus the `syn137/verified` context itself**, each with
     its conclusion on S′ and the source app's id.

   Any read that fails or is incomplete becomes `unreadable` in the facts. It
   is never omitted.
3. Dispatches `CarryCertificationForward(facts)` to S′'s stream.

The aggregate's rule: S is certified at the cited version, the first-parent
path from S′ reaches S, every commit on it is either a Base Merge (second
parent on the base branch **and** tree equal to the clean merge) or a
Mutation-only Commit, every prerequisite check concluded `success` from its
expected app, and nothing is `unreadable`. Otherwise it refuses, and S′ stays
unreviewed with no status. A real review is what it needs then. A carried
certification is revoked if S later stops being certified.

This covers 33 of the 66 older-head merges in section 1 (22 base merges and 11
`.mutations/` commits). The other 33 changed code and must be reviewed again.

## 7. GitHub App permission and the agent-token cap (security)

- **Posting needs `statuses: write`** on the App. That is
  `POST /repos/{owner}/{repo}/statuses/{sha}`. Reading the required checks
  needs `checks: read`, which the evidence plan already requires
  (`docs/plans/20261015_platform-dispatched-evidence.md`, the
  `required_check` step).
- **Whether the App has `statuses: write` today is unverified.** Nothing in
  the repo posts a status. The #2057 sample found no platform-authored status
  on any head. Check it with the live grant that `mint_agent_token` already
  reads: `GET /app/installations/{id}`, field `permissions.statuses`.
- **Agents must not be able to post this status.** Every Phase holds the
  installation's own grant, except that `actions` is capped at `read`
  (`syn_adapters/github/agent_token.py`, `CAPPED_PERMISSION = "actions"`;
  `infra/docs/github-app-security.md`, Token Scoping). A permission the App
  gains later reaches every Phase. So granting `statuses: write` without a cap
  would let a Phase post `syn137/verified: success` on its own commit.
- **Slice S4 therefore generalises the cap** to a set: `actions`, `statuses`
  and `checks`, each lowered to `read`. That ships and deploys **before** the
  App gains `statuses: write`, with the same ordering rule the evidence plan
  gave `actions`. A test mints a token from a grant that includes
  `statuses: write` and asserts the phase token has `read`.
- **A forged verdict.** A Phase cannot move a Head Certification by
  reporting `certified`, unless it is a Reviewing Phase by the frozen
  definition (`requires_verdict` and `review_target: platform`), of an execution of a workflow on the
  `SYN_VERIFIED_STATUS_REVIEW_WORKFLOWS` allowlist (section 8). The target
  must also be its platform-resolved Review Target. Cross-family verification
  stays a workflow property; this plan does not check models.
- Making the status required uses a ruleset rule pinned to the App's
  integration id, so only the App can satisfy it. That is safe only after the
  cap.

## 8. Feature flag (ADR-004)

`SYN_VERIFIED_STATUS_ENABLED` (default `false`),
`SYN_VERIFIED_STATUS_REPOSITORIES` (an allowlist, default empty) and
`SYN_VERIFIED_STATUS_REVIEW_WORKFLOWS` (the workflow ids whose Reviewing
Phases count, default empty), in a Pydantic settings class, regenerated into
`.env.example`. Enabling also records the publication epoch event (section 5).

- Recording (`ReviewVerdictRecorded`, `HeadReviewed` and the rest) is always
  on. It is Lane 1 truth, cheap, and it is what section 9 measures.
- Only `VerifiedStatusProcessManager`'s POST is gated. While the flag is off,
  its to-dos stay pending, and those that precede the epoch are marked
  `historical` when it is recorded.
- **Review-only success is not published until evidence is integrated (S8)**,
  because a certified review on a head whose declared evidence failed would
  otherwise read green. So S4 to S7 can ship and run dark, recording and
  measuring, but the flag is not turned on until S8.
- Turning it on is a deploy-time setting on the owner's VPS. Nothing ships
  enabled.

## 9. Measuring it

- **Baseline:** 86 of 200 merged agent PRs were certified on the head that
  merged (#2057).
- **Metric:** the share of merged agent PRs whose merged head carried
  `syn137/verified: success` at merge time. It is split into review, override
  and carry-forward, and also counts merges with `failure` or no status.
- **Read path:** `GET /heads/{owner}/{repo}/{sha}/certification`, a
  projection with a Pydantic response model and CLI types via `just codegen`.
  A script joins it with merged PRs over a window.
- **Decision rule for "required":** run two weeks with the flag on. If merges
  without `success` are only the ones overrides would have covered, propose
  the ruleset change to the owner with the numbers. An agent never changes
  the ruleset.

## 10. Certification state: the one table

`HeadCertification` derives its state from its stream with this table and no
other rule. S2, S5, S6 and S8 implement rows of it; each slice's tests cover
its rows plus the rows above them.

Inputs, as folded at the latest version:
- **Decision:** the latest explicit decision by stream order, a review
  (`certified` or `blocked`) or an override. A carry is not a decision.
- **Carry:** a live `CertificationCarried` (not revoked). Ignored when any
  explicit decision exists.
- **Evidence (S8):** for every evidence step planned for this head, its
  settled outcome. `all passed`, `some failed`, or `open` (not settled,
  `void`, `unavailable`, or declared with no plan). `none planned` when no
  step targets this head.

| # | Decision | Carry | Evidence | State |
|---|---|---|---|---|
| 1 | review `blocked` | any | any | `blocked` |
| 2 | review `certified` | any | `some failed` | `blocked` |
| 3 | review `certified` | any | `open` | `unreviewed` (not verified yet) |
| 4 | review `certified` | any | `all passed` or `none planned` | `certified` |
| 5 | override | any | `some failed` or `open` **named in the override** | `certified` |
| 6 | override | any | `some failed` or `open` not named in it | `blocked` / `unreviewed` as rows 2-3 |
| 7 | override | any | `all passed` or `none planned` | `certified` |
| 8 | none | live | evidence of the source head, as rows 2-4 | carried state |
| 9 | none | none or revoked | any | `unreviewed` |

What an override may bypass: **only evidence steps it names** (by gate and
step, with the reason and evidence link that settled them by other means, for
example the integration run #1968 used). An override never bypasses a later
blocked review (row 1 wins because it is later in the stream), and never
bypasses a step it does not name. Before S8 the Evidence column is always
`none planned`, so rows 1, 4, 7, 8 and 9 are the whole table, and publishing
stays off (section 8).

## 11. Test plan and slices

Each slice is sized for one `sdlc-implement` run. Each has unit tests (marker
`unit`) beside the code. Aggregates and ProcessManagers are tested against the
real event and projection-store contracts, not hand-rolled dicts.

| Slice | Change | Key tests |
|---|---|---|
| S0 | `review_target: platform` phase capability (schema, frozen at start, `check-workflows` refuses it with an agent-side checkout); before provisioning such a Phase the platform resolves the target (Own Push head, or the PR head via `RemoteBranchPort`), checks it out, reads it back, and records `ReviewTargetResolved`. A new workflow arm opts in with checkout-free verify prompts | target equals the pushed head; a moved branch is a Checkout Mismatch; the agent cannot change the recorded target; a phase without the capability gets no target; `check-workflows` rejects the capability on a prompt with `git checkout` |
| S1 | `ReviewVerdictRecorded` on WorkflowExecution, emitted from the command handler for Reviewing Phases with a `ReviewTargetResolved`; vocabulary | an implement Phase reporting `certified` emits nothing; an existing v3/v4 verify Phase (`requires_verdict`, no capability) emits nothing; a capable verify Phase emits its own target, not the run's first checkout; target and read-back mismatch emits nothing; replay of old streams emits nothing |
| S2 | HeadCertification aggregate, commands and events, `CertificationStateChanged` on every transition, the section 10 table rows 1, 4, 7, 9; vocabulary | each row as a test; latest decision wins by stream order; duplicate review ignored; override needs a reason; a no-op command emits no state change |
| S3 | `HeadReviewIntakeProcessManager` + coordinator wiring | replay writes to-dos with no dispatch; live dispatches once; restart mid-batch does not double-record |
| S4 | Agent-token cap for `statuses` and `checks`; `CommitStatusPort` + GitHub adapter; `VerifiedStatusProcessManager` behind the flag, with a durable lease per key | cap test; flag off posts nothing; pre-epoch to-dos never post; two workers cannot post out of order; an uncertain write is reconciled; the section 5 mapping, including success followed by a state change to `blocked` posts `failure` and to `unreviewed` posts `pending`; adapter contract test against the real endpoint shape |
| S5 | Override: API route, CLI command, event; operator identity and override permission at the route; table rows 5-7 (named evidence steps) | refused without a reason; refused for a workspace token or an unauthenticated internal call; a later blocked review supersedes it; it bypasses only the evidence steps it names |
| S6 | Carry-forward facts handler + clock wake + revocation; table row 8 | a base merge that brings in ordinary upstream code commits from main is **accepted** (they are off the first-parent path); a merge whose second parent is not on the base branch is refused; a merge whose tree differs from the clean merge is refused; a path that does not reach S is refused; `.mutations/`-only accepted; red or unreadable prerequisite refused; `syn137/verified` excluded from prerequisites; a repeated carry is a no-op; a carry never overrides a review; revoked when the source is blocked, and the revocation publishes `pending` |
| S7 | Certification read model, API, measurement script | counts state their scope; a fixture is pinned to a real recorded head |
| S8 (#2081) | Evidence intake and table rows 2, 3, 6: see below. `finalize_pr` reads `GET .../certification` instead of parsing manifests | every fail-open case Codex found on #2063 is a unit test here; declared evidence with no plan is `open`; a cleaned-head step is attributed to `after_sha` from `MutationPatchesRemoved`, never to S; a step with no resolvable repository/head is routed, not dropped; replay records nothing twice |

**S8 intake contract (a shipping criterion for S8).** A durable
`HeadEvidenceIntakeProcessManager`, the same shape as the review intake:
- Subscribes to `EvidenceRequested` (its `steps: list[EvidencePlanStep]`),
  `EvidenceStepSettled` (`outcome`, `head_sha_evidenced`, `gate_id`, `step`)
  and `MutationPatchesRemoved` (`gate_id`, `step`, `repository`,
  `before_sha`, `after_sha`), all on `origin/main` today, plus the recovery
  clock. It also reads the phase's `TASK_RESULT.evidence` declaration so a
  declared gate with no plan is an obligation, not an absence.
- Resolves each step's target head: `EvidencePlanStep.head_sha` when set; for
  `on_cleaned_head` steps (planned with `head_sha=None`) the `after_sha` of the
  gate's `MutationPatchesRemoved`; otherwise the step's `head_sha_evidenced`.
  A step whose repository or head cannot be resolved is a to-do in
  `unresolved`, retried on the clock and, after the gate closes, recorded as
  `open` against every head the execution reviewed in that repository: it
  can hold a head, never pass one.
- Dispatches typed commands, `PlanEvidenceForHead` and
  `RecordEvidenceForHead`, to the head's stream. To-dos are keyed
  `(execution_id, gate_id, step, repository, sha)`; the aggregate is
  idempotent on `(execution_id, gate_id, step)`, so replay and retries record
  once.

S4's cap must be deployed before the App permission changes. Publishing is
not enabled until S8, so success never means "reviewed but evidence unknown".
S8 is also what lets the next SDLC arm's `finalize_pr` shrink back toward
v4-precheck's length (#2081).

### On #2081: one model or two

One. #2081 asks for a per-head evidence verdict computed in code. That is
another input to the same question this plan answers: is this head good
enough to merge? So HeadCertification takes the evidence plan and
step settlements (`EvidenceRequested`, `EvidenceStepSettled`,
`MutationPatchesRemoved`) as facts, and section 10's table decides. The gate itself
still opens on any outcome; this is where the outcome finally counts. Two
per-head models would disagree on the same SHA and need reconciling. S8
extends the aggregate; it does not add a second one.

## 12. Open questions for the owner

1. **App permission.** Grant `statuses: write` once S4's cap is deployed? (It
   must not happen before.)
2. **Who may override?** Owner only, or the orchestrator agent too? If it is
   the agent, each override would need a recorded owner approval tied to that
   specific SHA.
3. **Latest decision wins.** Should a later blocked review really undo an
   owner override on the same SHA? Recommended: yes, because new evidence
   beats an old decision.
4. **Repositories and workflows.** syntropic137 only at first, or
   agentic-workspace too (its CODEOWNERS already gates merges)? And which
   workflow ids count as reviewers (the current suggestion is
   `sdlc-reverify-pr-v1` and the active implement arm)?
5. **Making it required** (after section 9's two weeks) is a ruleset change.
   That is the owner's decision alone.
