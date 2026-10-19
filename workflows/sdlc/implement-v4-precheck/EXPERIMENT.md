# sdlc-implement-v4-precheck: design note and preregistration (2026-10-14)

## Design note

### The one change

`sdlc-implement-v4-precheck` is `sdlc-implement-v3` plus an **evidence
precheck**. It is the first thing `verify`, `reverify` and `reverify_2` do
after the checkout, before any gate runs. It puts every problem with the
evidence into one of four classes:

| Class | Closed by | Repair round? |
|---|---|---|
| `REPAIRABLE` | the next `fix` phase | yes: the only class that can make a review BLOCKED |
| `FLAKE/INFRA` | one rerun (`gh run rerun <id> --failed`) | never |
| `ORCHESTRATOR_EVIDENCE` | the orchestrator, running the exact Docker/DB command given | never |
| `CI_GAP` | the orchestrator: a retarget, or a `.github/workflows/` patch | never |

The precheck covers the four checks the brief asked for:

1. `gh pr view --json mergeStateStatus,baseRefName,statusCheckRollup`:
   - `DIRTY` gives "merge main first", which is `REPAIRABLE`, since a fix
     phase can merge;
   - a base that is not the default branch gives "retarget", which is
     `CI_GAP`;
   - no checks gives "CI never ran: <reason>".
2. Each new or changed test file must have a CI job that runs it. When the
   fix is inside the branch, the item is `REPAIRABLE`. When the fix is in
   `.github/workflows/`, it is `CI_GAP` with a patch, because the workspace
   credential refuses any push that touches that directory. Whether a job
   collects the file is answered statically (its command, paths, matrix and
   marker, and `--collect-only` on the head); whether it passed is answered
   from a per-file CI line where the reporter prints one, else by running it
   on the head. An xdist log prints no file names, so a name missing from it
   proves nothing and is never a `CI_GAP`.
3. A failure in files the PR did not change, matching a known flake class, is
   `FLAKE/INFRA`. Eligibility for the class and eligibility for its rerun
   are separate: each failing step gets **one** rerun, ever. If that rerun
   fails the same way, the item stays `FLAKE/INFRA` with status `base defect:
   no more reruns`: never `REPAIRABLE`, never a round, no second rerun, and
   it closes when the same check is green on the default branch. A failing
   test the PR did not edit that exercises code the PR did edit is
   `REPAIRABLE`.
4. Docker, database or real-store evidence is `ORCHESTRATOR_EVIDENCE`, with
   the exact command.

`finalize_pr` reads the final report's `## Handed to the orchestrator`
table. **While any handoff is open it never marks the PR ready.** It retargets
and requests the rerun itself where it can, then posts one comment that opens
with `Certified pending orchestrator evidence` and gives each command. A
report with no handoff section counts as having open handoffs.

### Why it is shaped this way

- **Hide the decision in one place.** The four classes and the verdict rule
  ("`blocked` if and only if a `REPAIRABLE` item is open") live in ONE
  section of text, identical in all three review prompts. The test fails if
  the copies drift. The engine needs no change: the precheck only changes
  which items count toward `review_verdict`, and the aggregate already skips
  every round on `certified`.
- **The safety property is structural, not trusted.** (Structural in the
  workflow: the tests check the prompt text says this, and cannot show an
  agent obeys it. The A/B's mechanism check is what measures that.) If a verifier puts a
  real defect in a handoff class, the PR does not ship. It stays a draft
  with the item posted on it. An item whose class the verifier cannot
  evidence is `REPAIRABLE`. The worst-case cost of a wrong classification is
  a person's attention, not an escaped defect.
- **v3's shared CI section stays byte-equal.** `test_unrunnable_check_is_settled_by_ci.py`
  holds every copy of "A check this workspace cannot run is settled by CI on
  the same head SHA" identical. v4 is registered there too, so the two v3
  rules the precheck overrides are named inside the precheck section and not
  edited in place. A future change to the shared section still has to reach
  v4.
- **The rerun is requested, not assumed.** The GitHub App is documented as
  `Actions: Read` (`docs/deployment/github-app-setup.md`), so `gh run rerun`
  from a workspace will probably be refused. The prompts treat that 403 as
  expected and carry the command forward. They do not report it as a phase
  failure.

### What is held constant

Phase ids, order, agents (opus implements and fixes; codex `gpt-sol`
verifies, with an opus fallback), timeouts, skills, `requires_verdict`, the
two-round bound, and every prompt except `verify.md`, `reverify.md`,
`reverify_2.md` and `finalize_pr.md`. All of this is pinned by
`scripts/tests/test_implement_v4_precheck_variant.py`, which checks the
definitions and prompt text, including that finalize's handoff section never
instructs `gh pr ready` however the line wraps; it does not check what an
agent does. Every line that
differs outside the precheck section must name a precheck term.

### Deviations and provenance

- **Id.** The brief fixed `sdlc-implement-v4-precheck`. README `## Naming`
  would give `sdlc-implement-precheck-v1`. The chosen name says which
  baseline it varies.
- **Evidence.** The motivating paper cuts (PC-161, PC-163, PC-166, PC-167,
  PC-169, PC-179) and eval ideas E-13 and E-15 are in the orchestrator's
  external log and appear nowhere in this repository. Only the CI-matrix case
  has a citation in this repo: `docs/retrospectives/2026-10-13-provider-contract-day.md`
  (AW#49, 74 `scripted_agent` tests CI never ran).
- **Overlap.** Check 2 asks the same question as the checks treatment
  (`workflows/evals/verify-pinned-codex-checks/`, preregistered in
  `evals/verifier-seed-aw-v1/experiments/2026-10-13-checks-treatment.md`),
  which has not reported yet. Check 2 can *add* `REPAIRABLE` findings, while
  checks 1, 3 and 4 *remove* rounds. Its findings are therefore counted
  separately below, so the net effect can be split into its parts.

## Preregistration

### Question

Does classifying unfixable evidence before verification spend fewer repair
rounds per run, without letting more defects escape?

### Arms (one variable)

- **Control:** `sdlc-implement-v3`, as on `main` at the merge of this PR.
- **Treatment:** `sdlc-implement-v4-precheck`.

The only difference is the precheck, as described above.

### Hypothesis

Treatment runs spend fewer repair rounds (`fix` + `reverify` pairs) than
control runs. Their wall time to READY is no worse once handoffs are counted.
Their escaped findings are no higher.

**Possible outcomes, all legitimate:** fewer rounds with no escapes; no
difference (the precheck finds nothing to hand off on these tasks); fewer
rounds but more escapes (reject); more rounds, because check 2 added
findings.

### Sample

The **next 6 real implementation tasks** the orchestrator dispatches after
this workflow is installed, excluding `quickfix`-shaped tasks (README:
"is there anything to prove?"). Assignment alternates in dispatch order
(1: v4, 2: v3, 3: v4, ...), fixed now so that task choice cannot follow the
arm. No task runs on both arms. Each run is tagged
`experiment:v4-precheck-ab` plus `arm:control` or `arm:treatment` (tags
accept only `[a-z0-9._/:-]`, so `=` is rejected):

```
syn execution tag add <execution-id> experiment:v4-precheck-ab arm:treatment
syn execution tag add <execution-id> experiment:v4-precheck-ab arm:control
```

### Mechanism check (before any metric is read)

A treatment run counts only if every review report it produced (`verify`,
plus each `reverify*` that ran) has exactly one `Precheck:` line and a
`## Handed to the orchestrator` section, and `finalize_pr.md` copies the
`Precheck:` line. A run without these is a run where the treatment did not
happen. It is reported as void and replaced by the next task, not scored.

### Metrics

Read from stored records (`syn execution show <id>`, the PR's GitHub timeline
and artifacts), never from an agent's summary.

- **Primary: repair rounds per run.** The number of `fix*` phases that ran
  on the execution (0 to 2). Compare the sum over each arm's 3 runs.
- **Wall time to READY.** From execution start to the PR's
  `ready_for_review` timeline event, whoever marked it ready. For treatment
  runs this includes the time a person or the orchestrator took to clear the
  handoffs. Without that, the treatment would win just by stopping earlier.
  A PR not ready within 72h is censored at 72h, and the censoring is shown.
- **Guard: escaped findings.** Blocking findings raised on the PR within 14
  days of it being marked ready, by a human, a later review run or a revert.
  The treatment's count must not exceed the control's.
- **Secondary, treatment only:**
  - counts per class, summed from the `Precheck:` lines;
  - check-2 findings on their own (overlap with the checks treatment);
  - **misclassified handoffs:** handoffs that turned out to be the PR's own
    defect once the orchestrator ran them;
  - **reruns refused** with 403 (tests the `Actions: Read` assumption).
- **Cost:** total execution cost per arm, reported beside the primary metric.

### Decision rule

- **Adopt** (v4-precheck becomes the default implementation workflow, as a
  separate PR): the treatment's repair rounds are fewer than the control's,
  its escaped findings are no higher, its misclassified handoffs are 0, and
  its median time to READY is no worse.
- **Reject:** escaped findings are higher, or any misclassified handoff
  reached READY. A misclassified handoff that was *caught* while the PR was a
  draft is reported, and it does not reject the treatment on its own.
- **No difference** (equal rounds, or no handoffs in any treatment run) is
  reported as a result. The likely reading is that these 6 tasks did not
  hit the failure classes, not that the precheck failed.

### Stopping rule

Six scored runs (3 per arm), then stop and write the result here. A run that
fails for a platform reason (no verdict, a workspace that died) is
re-dispatched once on the same arm. If it fails again, it is recorded as an
error and is not replaced.

### Limits stated up front

- Three runs per arm. One task's difference is the whole result: this is a
  screen, not an estimate. The tasks are not matched, so the failure classes
  may simply not occur in one arm.
- The motivating evidence is from 2026-10-13/14 and external to the repo (see
  above). The base rate of these failure classes on the next six tasks is
  unknown.
- Handoffs move work from the agent to the orchestrator. The time-to-READY
  metric is there so that this transfer cannot read as a saving.
- `gpt-sol` is an alias. Record the resolved verifier model of every run. A
  run whose verifier fell back to claude is reported as non-cross-family.

## Results

Scored 2026-10-16 from stored records (execution phases, PR timelines, mutation-evidence runs). All six slots ran between 2026-10-15 01:25Z and 2026-10-16 08:2xZ. Three runs were void and replaced on the same arm, because they stopped before verify, so they have no Precheck line: exec-5a051b7a8649 (brief contradicted itself), exec-4e671cce1d13 (scope too big) and exec-873d0b0f78fe (premise false, already fixed upstream).

| Slot | Arm | Execution (replacements) | PR | fix* phases | Extra repair runs | Precheck line | Wall to READY | Defect found after certification (before merge) |
|---|---|---|---|---|---|---|---|---|
| 1 | T | exec-53a6bf1bdb7a | AgentParadise/agentic-workspace#76 | 0 | 1 (probes lost) | REPAIRABLE=0 FLAKE=1 EVIDENCE=1 | ~6.7h (includes a 3.5h orchestrator network outage) | none |
| 2 | C | exec-4f4906567185 | #1968 | 2 | 2 | n/a | not READY (blocked on an AW pin), censored | yes: runc not enforced (fixed in AW#79); found by orchestrator evidence |
| 3 | T | exec-05930ce02660 | #1975 | 2 | 1 | REPAIRABLE=1 FLAKE=1 EVIDENCE=2 | ~6.5h | yes: fencing bound did not hold on real Postgres; found by the handed-off evidence |
| 4 | C | exec-c1c810ecad3e -> exec-bdaf2eefdc46 | #1974 | 2 | 0 | n/a | ~5.2h (one platform re-dispatch) | none |
| 5 | T | exec-38c467ea16c7 -> exec-d6b475a9eb65 (+ exec-8fc649a67eea) | #1985 | 2 | 1 (2 rounds) | REPAIRABLE=2 FLAKE=1 EVIDENCE=2 | ~14h (account limit, disk-full outage) | none escaped; 2 REPAIRABLE findings caught before merge |
| 6 | C | exec-77b0e3675e65 -> exec-b3324a164c2a (+ exec-e0bfad000b22) | #1981 | 2 | 1 | n/a | ~12h (account limit, disk-full outage) | yes: integration tests never collected (fixture ScopeMismatch); found by orchestrator evidence |

**Mechanism check:** every treatment run's reports carried exactly one `Precheck:` line and a `## Handed to the orchestrator` section. Every handoff the orchestrator ran was the PR's own evidence gap, not a misclassified defect, so **misclassified handoffs = 0**. No `gh run rerun` was attempted by the agent (403 expected, not tested).

**Primary metric (repair rounds):** treatment 4 `fix*` phases vs control 6. Including extra repair runs launched after the bound: treatment 7 rounds vs control 9.

**Wall time to READY:** median treatment ~6.7h vs control ~12h (one control slot censored). Three slots were confounded by platform incidents: the outage, the account weekly limit and the disk filling up.

**Guard (escaped findings):** none so far. The 14-day window closes 2026-10-30.

**Cost:** not recorded per arm (the account switch split the usage windows).

**Decision (provisional, by the preregistered rule):** ADOPT, pending the escape window. The treatment used fewer repair rounds, showed no more escaped findings, had 0 misclassified handoffs and a median time to READY no worse. The larger finding cuts across both arms: in 3 of 6 slots the platform verifier certified a head whose real-service tests had never run, and orchestrator-run evidence found a real defect each time. That is the case for the platform-dispatched evidence plan (docs/plans/20261015_platform-dispatched-evidence.md on #1874). Per that plan's decision 4, cut `sdlc-implement-v5` as v4 plus evidence declarations, and do not edit v4 in place.

**Limits:** n=3 per arm; the tasks differ in kind; incidents add noise to wall time. Re-score once the escape window closes.

