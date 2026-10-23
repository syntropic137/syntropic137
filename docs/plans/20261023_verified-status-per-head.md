# Plan: a `syn137/verified` commit status per reviewed head (#2057, with #2081)

**Status.** Proposed, 2026-10-23. Docs only: no code changes in this PR. Every
citation to `main` was read at `origin/main` while writing it.

**Owner decisions needed** are collected in [section 11](#11-open-questions-for-the-owner).

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
- **The reviewed commit is already a domain fact.** Every Phase's
  provisioning records its Starting Checkout, read back from the workspace
  and verified against the pin (#967): `WorkspaceProvisionedForPhase.checked_out_commits`
  (`domain/aggregate_execution/phase_step_events.py`, `workspace_provisioned_event`).
  For a verify Phase, that is exactly the commit the verifier read. The
  agent's own text ("Certified SHA: ...") is never used.

What is missing is a record joining the two per commit, and something that
tells GitHub.

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

- **Reviewed Head.** The commit, per repository, that a reviewing Phase's
  Starting Checkout recorded. That is what the Review Verdict is about. It is
  never taken from the agent's report.
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
  an earlier certified head. That happens only when every commit between them
  is a Base Merge or a Mutation-only Commit, and the required checks are green
  on the later head (section 6).
- **Verified Status.** The GitHub commit status, context `syn137/verified`,
  that publishes a Head Certification. It is a projection of a Lane 1 fact
  onto the forge, never a source of truth: the aggregate is the truth.

Not used: **Approval** (a GitHub review is an approval; this is not a review),
and **Verdict** alone (an eval Verdict is `PASS`/`FAIL`/`ERROR` about a Run;
see that entry).

## 4. Ownership and events

### 4.1 WorkflowExecution (existing aggregate) gains one event

`ReviewVerdictRecorded`, emitted when a reviewing Phase completes, meaning a
Phase that reported a Review Verdict. It carries:

| Field | Source |
|---|---|
| `execution_id`, `phase_id`, `workflow_id` | the aggregate |
| `verdict` | `ReviewRecord.of(phase_id)` |
| `reviewed_heads: list[SourceCommit]` | that Phase's own `WorkspaceProvisionedForPhase.checked_out_commits` |
| `verifier_model` | `AgentExecutionCompleted.agent_model` for that Phase |
| `pull_requests: list[(repository, number)]` | `ObservedHead.open_pr_number` from that Phase's `ArtifactsCollectedForPhase`, when observed |

Why a new event rather than letting a subscriber join three: the aggregate
already holds all three facts, and joining them is a rule. Rules belong in
the aggregate, not in a ProcessManager. The aggregate keeps only the first
provisioning's checkout today (`_starting_checkout`), so S1 adds a per-Phase
map of checkouts.

A Phase with no recorded checkout (an old event, or a Phase with no repo
checkout) emits `reviewed_heads: []`. Nothing downstream acts on an empty
list. That is the honest reading: nobody knows which commit it judged.

### 4.2 HeadCertification (new aggregate, orchestration)

`domain/aggregate_head_certification/HeadCertificationAggregate.py`. One
stream per `repository@sha`, created with `ExpectedVersion.NoStream`
(stream-per-unique-value). It decides; nothing else does.

| Command | Event | Rule |
|---|---|---|
| `RecordReviewOfHead` | `HeadReviewed` | Idempotent on `(execution_id, phase_id)`: a duplicate records nothing. |
| `OverrideCertification` | `CertificationOverridden` | Needs actor, reason and evidence link. Refused for an empty reason. |
| `CarryCertificationForward` | `CertificationCarried` | Needs the facts in section 6. The aggregate re-checks them; refused unless every commit qualifies and the required checks are green. |

State: the ordered history plus `state`. **The latest decision wins, by
stream order.** A blocked review after an override makes the head blocked
again: new evidence beats an old decision. An override after a block makes it
certified.

## 5. ProcessManagers (Processor To-Do List, ADR-025)

Both live in `slices/publish_verified_status/` and follow
`QuarantineNoticeProcessManager`: `handle_event` writes to-do records and is
pure and replay-safe, and `process_pending` does the work, live only.

**`HeadReviewIntakeProcessManager`.**
- Subscribes to `ReviewVerdictRecorded`.
- To-do: one per `(execution_id, phase_id, repository, sha)`.
- Process: dispatch `RecordReviewOfHead` to that head's stream.
- No forge I/O.

**`VerifiedStatusProcessManager`.**
- Subscribes to `HeadReviewed`, `CertificationOverridden` and `CertificationCarried`.
  It also subscribes to the recovery clock (`InventoryReconciliationSweep`)
  for carry-forward checks and retries.
- To-do: one per `(repository, sha, context)`, holding the desired state and
  the aggregate version it came from.
- Process: post the status when `posted_version < desired_version`.

**Idempotency, keyed on `(sha, context)`.** A GitHub status is append-only per
SHA, and the latest one with a given context wins. Re-posting the same state
is harmless, so a crash between POST and recording the post just posts it
again. The to-do key makes repeats cheap, not necessary for correctness.

**Replay safety.**
- `handle_event` never calls the forge.
- A first deploy replays every historical review. Each to-do records the
  event's `recorded_at`, and `process_pending` marks to-dos older than the
  flag's enable time as `historical` and posts nothing for them, so history
  never paints statuses on old SHAs.
- Restarts resume from the checkpoint as usual.

## 6. Carry-forward

The PR head moves past a certified SHA. There is no stored "PR head moved"
event (`github/domain/events/` holds only installation and trigger events), so
the clock tick wakes the check, the same way the Quarantine Notice is woken.

For each certified head with an open PR, `process_pending`:

1. Asks the forge for the PR's head S′. It stops if S′ equals S.
2. Lists the commits S..S′ with their parents and the paths each changed, and
   reads the conclusions of the base branch's required checks on S′. Required
   checks are the union of the paginated rules API and classic protection; a
   404 from classic protection means none is configured. These are the same
   rules the v6 workflow uses.
3. Dispatches `CarryCertificationForward(from=S, to=S′, facts)` to S′'s stream.

The aggregate's rule. Every commit in S..S′ must be one of:

- **A Base Merge.** It has two parents, and its second parent is on the base
  branch. Every path it changes relative to its first parent is a path the
  base branch changed between the two merge-bases. Equivalently: no
  conflict-resolution edits.
- **A Mutation-only Commit.** Every path it changes is under `.mutations/`.

And every required check concluded `success` on S′. If any condition fails, S′
stays unreviewed and gets no status. A real review is what it needs then.

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
- Making the status required uses a ruleset rule pinned to the App's
  integration id, so only the App can satisfy it. That is safe only after the
  cap.

## 8. Feature flag (ADR-004)

`SYN_VERIFIED_STATUS_ENABLED` (default `false`) and
`SYN_VERIFIED_STATUS_REPOSITORIES` (an allowlist, default empty), in a
Pydantic settings class, regenerated into `.env.example`.

- Recording (`ReviewVerdictRecorded`, `HeadReviewed` and the rest) is always
  on. It is Lane 1 truth, cheap, and it is what section 9 measures.
- Only `VerifiedStatusProcessManager`'s POST is gated. While the flag is off,
  its to-dos stay pending and are marked `historical` at enable time.
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

## 10. Test plan and slices

Each slice is sized for one `sdlc-implement` run. Each has unit tests (marker
`unit`) beside the code. Aggregates and ProcessManagers are tested against the
real event and projection-store contracts, not hand-rolled dicts.

| Slice | Change | Key tests |
|---|---|---|
| S1 | `ReviewVerdictRecorded` on WorkflowExecution, per-Phase checkout map, vocabulary "Reviewed Head" | a verify Phase emits it with its own checkout, not the run's first; no verdict means no event; a checkout-less Phase gives `reviewed_heads=[]`; replay of old streams is unchanged |
| S2 | HeadCertification aggregate, commands and events, vocabulary | latest decision wins by stream order; duplicate review ignored; override needs a reason; carry rule accepts only Base Merge and Mutation-only Commit, with required checks green |
| S3 | `HeadReviewIntakeProcessManager` + coordinator wiring | replay writes to-dos with no dispatch; live dispatches once; restart mid-batch does not double-record |
| S4 | Agent-token cap for `statuses` and `checks`; `CommitStatusPort` + GitHub adapter; `VerifiedStatusProcessManager` behind the flag | cap test; flag off posts nothing; `historical` to-dos never post; a re-post after a crash is harmless; adapter contract test against the real endpoint shape |
| S5 | Override: API route, CLI command, event; actor taken from the authenticated caller | refused without a reason; a later blocked review supersedes it |
| S6 | Carry-forward facts handler + clock wake | merge with conflict edits refused; `.mutations/`-only accepted; red required check refused; S′ == S is a no-op |
| S7 | Certification read model, API, measurement script | counts state their scope; a fixture is pinned to a real recorded head |
| S8 (#2081) | Evidence input: `EvidenceSettled` facts for a head feed HeadCertification; `finalize_pr` reads `GET .../certification` instead of parsing manifests | every fail-open case Codex found on #2063 is a unit test here |

S4's cap must be deployed before the App permission changes. S8 is what lets
the next SDLC arm's `finalize_pr` shrink back toward v4-precheck's length
(#2081).

### On #2081: one model or two

One. #2081 asks for a per-head evidence verdict computed in code. That is
another input to the same question this plan answers: is this head good
enough to merge? So HeadCertification takes evidence settlements as facts,
and its state becomes certified only when the latest review certified the
head **and** no evidence declared for that head is unsettled or failed. Two
per-head models would disagree on the same SHA and need reconciling. S8
extends the aggregate; it does not add a second one.

## 11. Open questions for the owner

1. **App permission.** Grant `statuses: write` once S4's cap is deployed? (It
   must not happen before.)
2. **Who may override?** Owner only, or the orchestrator agent with the
   owner's standing approval recorded per override?
3. **Latest decision wins.** Should a later blocked review really undo an
   owner override on the same SHA? Recommended: yes, because new evidence
   beats an old decision.
4. **Repositories.** syntropic137 only at first, or agentic-workspace too (its
   CODEOWNERS already gates merges)?
5. **Making it required** (after section 9's two weeks) is a ruleset change.
   That is the owner's decision alone.
