# sdlc-implement-v7: design note and preregistration (2026-10-21, v7 cut 2026-10-23)

**Lineage.** This arm was first cut and run as `sdlc-implement-v5` (definition at
commit `9d4278c51`, installed on the owner VPS 2026-10-23). It ran twice, as a
live check and not as part of the A/B: `exec-47d6ab7275be` (the premise phase
refuted a stale task, so nothing was pushed) and `exec-ac271b4ad91a` (certified on
round 0, PR #2080). That second run found papercut PC-241: finalize left the
certified PR in draft over two Vercel preview statuses that `main` does not
require, which failed "rate limited" on apps the diff never touched. Workflow ids
are immutable once run, so the fix was cut as `sdlc-implement-v6` rather than
reinstalled over v5. The two v5 runs are not scored.

`sdlc-implement-v6` (definition at `959affd6c`) ran once, as a live check:
`exec-ea452869d0b1` on #1433 part 1, certified on round 0, PR #2083. It
exercised a real capability gap for the first time: verify wrote
`Capability gaps: ... database=1` with a `capability=database` row, because CI
skips the real-store `test_list_detail_parity.py` on PRs to `main`, and
finalize held the PR in draft on it. The declared integration evidence never
got a manifest ("declared, no manifest"), because the platform evidence gate is
built but never wired (#2085). It also showed why v6 cannot keep its PC-241
fix: classic branch protection answers the App token with HTTP 403 "Resource
not accessible by integration" (this repository protects `main` with a
ruleset), and v6 treated that 403 as an unreadable required set. Every v6 run on
this repository therefore fails closed, exactly as v4-precheck behaves, and the
required-checks rule never takes effect. v7 reads the rulesets first; the v6 run
is not scored either.

## Design note

### The change

`sdlc-implement-v7` is `sdlc-implement-v4-precheck` plus **evidence
declarations and capability gaps** (#2060). It is the v5 that
v4-precheck's EXPERIMENT.md decision 4 called for ("cut `sdlc-implement-v5`
as v4 plus evidence declarations, and do not edit v4 in place"), with the
prompt contract of `docs/plans/20261015_platform-dispatched-evidence.md`
section A.11. It changes seven prompts and nothing else. v6 added one more
section to four of them for PC-241 (last row), and v7 changed how that section
reads the required set:

| Prompt | Adds |
|---|---|
| `verify`, `reverify`, `reverify_2` | one shared section, `## Capability gaps and declared evidence`: check the workspace has the gate's tools, install what policy allows, otherwise record a capability gap as an `ORCHESTRATOR_EVIDENCE` row naming `capability=<name>`; declare integration and mutation rows in `TASK_RESULT.evidence`; judge a platform-evidence manifest when one exists; a `Capability gaps:` count line |
| `fix`, `fix_2` | one shared section: a finding that cannot be proven here is reported under `## Capability gaps` before any work, never refused after it; declare committed `.mutations/` |
| `implement` | declare committed `.mutations/` |
| `finalize_pr` | read the platform-evidence manifest (it closes declared rows only when complete, every step passed and `required_check` passed); accept the platform's recorded patch-removal commit as the head; list open gaps under `## Needs a capable workspace`; copy the `Capability gaps:` and `Platform evidence:` lines |
| `verify`, `reverify`, `reverify_2`, `finalize_pr` (v6, v7) | `## Only a check the base branch requires can hold this PR` (reviews) and `## Only a required check holds the PR in draft` (finalize): read the base branch's required checks; a non-required check failing for a cause outside the diff is listed under `Not required, not holding` and never holds a certified PR in draft; a non-required check the diff breaks is still `REPAIRABLE`. **v7:** the rulesets endpoint (paginated) is the source; classic protection is unioned in when it answers, and a 404 or 403 from it is a note, not a failure; only a failed rulesets read, or a classic error other than 404 or 403, makes the set unreadable, and then every check is treated as required, as in v4-precheck |

**The trade-off v7 accepts.** A check required only by classic branch
protection is invisible when classic protection answers 403, so v7 would treat
it as not required. On this repository there is none: the owner protects
`main` with a ruleset, and classic protection returns 404 even to the owner's
token. A repository that still requires checks through classic protection
should grant the App read access to branch administration, or keep running
v4-precheck.

The capability names are a closed list: `nested_docker`, `database`,
`event_store`, `live_api`, `other`. They are what the orchestrator routes on:
today to CI evidence or a run it does itself, and once capability matching
(`docs/plans/20261014_capability-matching-on-claim.md`, #1995) and an E2B
pool (#1915-#1919) exist, to a workspace that has the capability.

### Why

From 2026-10-01 to 10-21 on the owner VPS, 39 of v3's fix-round refusals
needed evidence the workspace could not produce (Docker, integration tests
against a real store, mutation runs, a live API). Each cost a fix round, about
$2-3 and 27 minutes, and then refused. v4-precheck stopped the reviewer from
spending rounds on this; it did not stop the fix phase from starting the work,
and it left the evidence for a person to run by hand.

### What is held constant

Every field of the workflow YAML except id, name and description; every phase's
model, provider, timeout, skills and tools; every other line of every prompt.
`scripts/tests/test_implement_v7_variant.py` pins it.

### What the declaration half needs

The `TASK_RESULT.evidence` entries are only dispatched once the platform
evidence gate is wired, and on 2026-10-23 it is not: no production code builds
an `EvidenceGatePolicy`, and the `SYN_EVIDENCE_GATE_ENABLED` setting its
docstring names does not exist (#2085, plan section A.15 PRs 4, 6, 7, 8). Until
then the entries are recorded, finalize writes `Platform evidence: declared, no
manifest` and holds the PR in draft, and the orchestrator dispatches the
evidence by hand (`integration-evidence.yml`, `mutation-evidence.yml`). The
capability half is measurable on its own.

## Preregistration

### Question

Does adding capability gaps and evidence declarations to v4-precheck cut the
repair work spent on evidence a workspace cannot produce, without more escaped
defects?

### Arms

- **Control:** `sdlc-implement-v4-precheck`.
- **Treatment:** `sdlc-implement-v7`.

This is two variables, not one: the capability-gap change and PC-241's
required-checks rule. The required-checks rule only changes the outcome when a
non-required check fails, so the primary metric is read only on **pairs** in
which neither arm saw one. Whether a run saw one is decided by the scorer from
GitHub's own check data (below), identically for both arms, never from the
treatment's `Not required, not holding` text, which the control does not
write.

Same task set, same models, same deployment flags for both arms in a batch.

### Hypothesis

Treatment runs spend fewer fix rounds on unfixable evidence and have fewer
fix-phase refusals, with escaped findings no higher.

### Sample (frozen 2026-10-23, rewritten for v7)

**Why not merged changes from their old base.** The v6 sample re-implemented
six merged PRs from the commit before each merged. `sdlc-implement` cannot start
from an old base: it branches from today's `main` and opens a real PR, so each
run would duplicate merged work on a moved base (the gap #2055's replay harness
closes). Open issues dispatched as pairs run on today's platform with no new
tooling, and the only cost is one closed PR per pair; waiting for #2055 would
leave the capability half unmeasured for weeks.

**Selection rule, fixed now.** At the first dispatch, list the open issues in
`syntropic137/syntropic137` that are unassigned, have the Launch or Post-Launch
milestone, carry `bug` or `tech-debt`, are not gated on a release or an owner
decision in their body, and are not the subject of an open PR. Of those, take,
in ascending issue number:

- the **five** lowest-numbered whose body names a path under
  `apps/*/tests/integration/`, a `docker`/`compose` file, `testcontainers`, or
  mutation evidence (the evidence class v7 targets), and
- the **one** lowest-numbered whose body names none of those (the control
  task: a capability gap reported on it is spurious).

Six tasks, one run per arm, twelve runs, six pairs. The list and the snapshot
time are written under Results before the first dispatch. No task is added,
swapped or dropped after it.

**Brief and order.** Both arms get the identical brief: the issue body verbatim,
then one line naming the issue. A pair's two runs are dispatched back to back on
the same `main`; odd-numbered pairs dispatch the treatment first, even-numbered
the control first, so drift on `main` does not favour one arm.

**Base SHA per arm, and the mismatch rule.** Back-to-back dispatch does not
freeze `main`: each implement phase fetches and merges the `origin/main` it
finds. So each arm's base is recorded, not assumed. A run's base is
`git merge-base <its first pushed SHA> origin/main`, cross-checked against the
`origin/main` SHA its implement report names. Both are written under Results
beside the pair. If the two arms' bases differ, list the commits between them
(`git log --name-only <older>..<newer>`). If any of those commits touches a file
that either arm's diff touches, the pair is excluded as a whole, with that
reason. If none does, the pair is scored. This rule is fixed before the first
dispatch.

**Two PRs per issue, one lands.** Both PRs are second-verified with
`sdlc-reverify-pr-v1`, the same for both arms, and those findings are the
quality guard below. Which PR may land is fixed per pair before dispatch,
alternating with the pair number (pair 1 the treatment's, pair 2 the
control's, and so on), and only if that PR is certified and merges under the
usual rules. The other is closed unmerged with a comment linking this file.
If the designated PR cannot land, neither lands, and the issue goes back to the
ordinary queue.

Cost, estimated: about $6 per run from the live checks, so about $75 for the
twelve runs plus the twelve second verifications.

Power, honestly: six pairs detect only a large effect. A paired sign test
needs all of the scoreable pairs to favour one arm before it reaches p < 0.05
(5 of 5 gives p = 0.031 one-sided). Read anything short of that as
directional, and report every pair's difference rather than a single total.

### Sample amendment (2026-10-23, before any dispatch)

The selection rule above was applied at 2026-10-23T20:38:40Z and produced an unrunnable
sample: requiring the `bug` or `tech-debt` label left one recent evidence-class
issue, and the older matches were stale or oversized (#750 names the retired
agentic-primitives image, #772 is a spec, #143/#145 are architecture
refactors). Nothing had been dispatched, so the rule is amended once, here, and
frozen again:

- open, unassigned, created on or after 2026-09-25 (the agentic-workspace
  cutover; older issues name systems that no longer exist), milestone Launch or
  Post-Launch, any label except `architecture`, `enhancement`, `scale`,
  `scaling`; title not starting `spec`, `RFC` or `Epic`; not gated on a
  release or an owner decision; not referenced by an open PR;
- evidence class: the body names `tests/integration`, an integration test,
  `testcontainers`, `docker`, `compose`, mutation evidence, a real store,
  Postgres, TimescaleDB or the event store;
- the five lowest-numbered evidence-class issues and the lowest-numbered
  other one (the control).

Sample at 2026-10-23T20:38:40Z:

| Pair | Issue | Class | First arm | Lands |
|---|---|---|---|---|
| 1 | #1431 pit_stop.sh mixed-version staging | evidence | v7 | v7 |
| 2 | #1509 live evidence for session-discovery rows | evidence | v4-precheck | v4-precheck |
| 3 | #1511 pit-stop swaps images but not compose | evidence | v7 | v7 |
| 4 | #1516 capture degraded on executions | evidence | v4-precheck | v4-precheck |
| 5 | #1553 event store OOM under replay subscriptions | evidence | v7 | v7 |
| 6 | #1424 vendor transcript parsing outside adapters | control | v4-precheck | v4-precheck |

A task whose premise phase refutes it in both arms is excluded as a pair and
not replaced: the premise phase is part of what is measured.

### Mechanism check (before any metric is read)

For each treatment run: did each review write a `Capability gaps:` line, did
each `ORCHESTRATOR_EVIDENCE` row carry `capability=`, did any declared
`evidence` entry get refused by the platform (look for refused declarations in
the phase's stored result), and did finalize write `Platform evidence:`. A run
where the mechanism did not fire is reported, not scored.

### Metrics

- **Primary:** fix rounds whose scope was only unfixable evidence, as a
  **paired difference** (treatment minus control) per task, over the
  scoreable pairs. Reported per pair and as the sign count.
- **Secondary:** fix-phase refusals per arm; capability gaps by name;
  declared entries refused by the parser; gaps that turned out to be the
  PR's own defect once run (misclassified).
- **Guard:** findings from the `sdlc-reverify-pr-v1` second verification of
  every PR, both arms, counted per pair. The treatment's count must not exceed
  the control's. Escaped findings within 14 days of READY are also recorded
  for the PR that lands, but only one arm lands per pair, so they are
  diagnostic, not part of the decision.
- **Cost and time:** total cost and wall-clock per arm, from the stored
  execution record, reported beside the primary metric.

### Decision rule

- **Adopt:** fewer primary-metric rounds, second-verification findings no
  higher, 0 misclassified gaps that reached READY, cost per arm no higher.
- **Reject:** second-verification findings higher, or a misclassified gap
  reached READY.
- **No difference** is a result: the tasks did not hit the class.

### Scoring, the same for both arms

- **Non-required failures.** At the start of the batch, read the base
  branch's required set once, the way v7's prompts read it (rulesets, plus
  classic protection when it answers). For each run, take **every head SHA it
  pushed**: the execution's pushed SHAs and branch continuation history from
  `GET /executions/<id>`, joined with the PR's commit list. A failure on an
  early head can cost the control a repair round and then vanish after the next
  push, so the final head alone is not enough. For each of those SHAs, list the
  failing check runs and commit statuses with `gh api
  repos/<o>/<r>/commits/<sha>/check-runs` and `.../status`. Capture this right
  after the run ends and **before** its second verification pushes anything,
  and store the capture under Results. A run saw a non-required failure if any
  failing name, on any of its heads, is not in that set.
- **Exclusion is by pair.** If either run of a pair saw a non-required
  failure, or either run is not scored (the mechanism check, or a platform
  failure that its one re-dispatch did not clear), the whole pair leaves the
  primary metric. Excluded pairs are still listed, with the reason.
- **Unfixable-evidence rounds.** A fix round counts when every finding it was
  handed is one the round's own verify report or fix report places outside
  what the workspace can produce (Docker, a database, a live API, a CI-only
  check). The scorer applies the same rubric to both arms, reading the
  findings and not the treatment-only headings.

### Stopping rule

The twelve runs and their twelve second verifications, then stop and write the
result here. No task is added,
swapped or dropped after the first dispatch. A run that fails for a platform
reason is re-dispatched once on the same arm; if it fails again, its pair is
excluded as above.

## Results

The A/B has not run. The v5 live checks (lineage, above) exercised the
`Capability gaps:` line (all zero) and the `Needs a capable workspace` heading
(`None.`). The v6 live check exercised a real gap (`database=1`) and an
evidence declaration, which got no manifest because the gate is not wired
(#2085). v7 itself has not run.
