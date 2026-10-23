# sdlc-implement-v6: design note and preregistration (2026-10-21, v6 cut 2026-10-23)

**Lineage.** This arm was first cut and run as `sdlc-implement-v5` (definition at
commit `9d4278c51`, installed on the owner VPS 2026-10-23). It ran twice, as a
live check and not as part of the A/B: `exec-47d6ab7275be` (the premise phase
refuted a stale task, so nothing was pushed) and `exec-ac271b4ad91a` (certified on
round 0, PR #2080). That second run found papercut PC-241: finalize left the
certified PR in draft over two Vercel preview statuses that `main` does not
require, which failed "rate limited" on apps the diff never touched. Workflow ids
are immutable once run, so the fix is cut as `sdlc-implement-v6` rather than
reinstalled over v5. The two v5 runs are not scored.

## Design note

### The change

`sdlc-implement-v6` is `sdlc-implement-v4-precheck` plus **evidence
declarations and capability gaps** (#2060). It is the v5 that
v4-precheck's EXPERIMENT.md decision 4 called for ("cut `sdlc-implement-v5`
as v4 plus evidence declarations, and do not edit v4 in place"), with the
prompt contract of `docs/plans/20261015_platform-dispatched-evidence.md`
section A.11. It changes seven prompts and nothing else. v6 adds one more
section to four of them for PC-241 (last row):

| Prompt | Adds |
|---|---|
| `verify`, `reverify`, `reverify_2` | one shared section, `## Capability gaps and declared evidence`: check the workspace has the gate's tools, install what policy allows, otherwise record a capability gap as an `ORCHESTRATOR_EVIDENCE` row naming `capability=<name>`; declare integration and mutation rows in `TASK_RESULT.evidence`; judge a platform-evidence manifest when one exists; a `Capability gaps:` count line |
| `fix`, `fix_2` | one shared section: a finding that cannot be proven here is reported under `## Capability gaps` before any work, never refused after it; declare committed `.mutations/` |
| `implement` | declare committed `.mutations/` |
| `finalize_pr` | read the platform-evidence manifest (it closes declared rows only when complete, every step passed and `required_check` passed); accept the platform's recorded patch-removal commit as the head; list open gaps under `## Needs a capable workspace`; copy the `Capability gaps:` and `Platform evidence:` lines |
| `verify`, `reverify`, `reverify_2`, `finalize_pr` (v6) | `## Only a check the base branch requires can hold this PR` (reviews) and `## Only a required check holds the PR in draft` (finalize): read the base branch's required checks; a non-required check failing for a cause outside the diff is listed under `Not required, not holding` and never holds a certified PR in draft; a non-required check the diff breaks is still `REPAIRABLE`; if the required set cannot be read, every check is treated as required, as in v4-precheck |

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
`scripts/tests/test_implement_v6_variant.py` pins it.

### What the declaration half needs

The `TASK_RESULT.evidence` entries are only dispatched where the deployment
runs with `SYN_EVIDENCE_GATE_ENABLED`. Without it, the entries are recorded and
the rows stay ordinary handoffs, so the capability half is still measurable on
its own. A run's report says which case applied (`Platform evidence: none`).

## Preregistration

### Question

Does adding capability gaps and evidence declarations to v4-precheck cut the
repair work spent on evidence a workspace cannot produce, without more escaped
defects?

### Arms

- **Control:** `sdlc-implement-v4-precheck`.
- **Treatment:** `sdlc-implement-v6`.

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

### Sample (frozen 2026-10-23)

Exactly six tasks, each run once per arm: twelve runs, six matched pairs. Each
task re-implements a merged change from the commit main was at just before it
merged (the merge commit's first parent), so the fix is absent from the base.
The task brief is the PR's linked issue, or the PR's own description where it
links none, with the fix's diff and hidden tests withheld. Both arms get the
identical brief text and base SHA.

| Task | Base SHA | Expected evidence |
|---|---|---|
| #2036 (issue #2021) | `87ac1cc32cbf6df0df022b3a3b4a47f786edf722` | mutation |
| #2038 (issue #1055) | `538aac945a73d0722934b5274b3128b1c7f3f340` | mutation |
| #2040 (issue #2030) | `68416b9c9193a9fe3b297bfff548f9f8578b6b5d` | mutation |
| #1968 (PR description) | `74ceba50c6b523d139271562b40527f21172c67b` | Docker, integration, mutation |
| #1922 (PR description) | `ab74ed13b847ef8bff89fa0095cdce972423648d` | Docker (compose) |
| #1144 part 2, `_run_headless` (control) | `a35a86e9e6388c558cc55c62734d88071808958b` | none |

The control task needs no external evidence, so a capability gap reported on
it is spurious. The "expected evidence" column is the dispatcher's reading of
each original PR's history; it is not used for scoring.

Power, honestly: six pairs detect only a large effect. A paired sign test
needs all of the scoreable pairs to favour one arm before it reaches p < 0.05
(5 of 5 gives p = 0.031 one-sided). Read anything short of that as
directional, and report every pair's difference rather than a single total.

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
- **Guard:** escaped findings within 14 days of READY, as v4-precheck defines
  them. The treatment's count must not exceed the control's.
- **Cost and time:** total cost and wall-clock per arm, from the stored
  execution record, reported beside the primary metric.

### Decision rule

- **Adopt:** fewer primary-metric rounds, escaped findings no higher, 0
  misclassified gaps that reached READY, cost per arm no higher.
- **Reject:** escaped findings higher, or a misclassified gap reached READY.
- **No difference** is a result: the tasks did not hit the class.

### Scoring, the same for both arms

- **Non-required failures.** At the start of the batch, read the base
  branch's required set once (the union of rules and classic protection, as
  the prompts read it). For each run, list the failing check runs and
  commit statuses on its final head with `gh api
  repos/<o>/<r>/commits/<sha>/check-runs` and `.../status`. A run saw a
  non-required failure if any failing name is not in that set.
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

The twelve runs above, then stop and write the result here. No task is added,
swapped or dropped after the first dispatch. A run that fails for a platform
reason is re-dispatched once on the same arm; if it fails again, its pair is
excluded as above.

## Results

The A/B has not run. The v5 live checks (lineage, above) exercised the
`Capability gaps:` line (all zero) and the `Needs a capable workspace` heading
(`None.`). They did not exercise a real gap or an evidence declaration.
