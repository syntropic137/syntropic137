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
non-required check fails, so each run's report says whether any did (the
`Not required, not holding` list), and the primary metric is read on the runs
where none did.

Same task set, same models, same deployment flags for both arms in a batch.

### Hypothesis

Treatment runs spend fewer fix rounds on unfixable evidence and have fewer
fix-phase refusals, with escaped findings no higher.

### Sample

At least 3 tasks per arm whose change needs Docker, a database or mutation
evidence to verify (the tasks behind #2036, #2038, #2040, #1968, #1922 are
the candidates), plus 1 task per arm that needs none, as a control for
spurious gaps. Each task runs once per arm.

### Mechanism check (before any metric is read)

For each treatment run: did each review write a `Capability gaps:` line, did
each `ORCHESTRATOR_EVIDENCE` row carry `capability=`, did any declared
`evidence` entry get refused by the platform (look for refused declarations in
the phase's stored result), and did finalize write `Platform evidence:`. A run
where the mechanism did not fire is reported, not scored.

### Metrics

- **Primary:** fix rounds whose scope was only unfixable evidence, per arm.
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

### Stopping rule

The sample above, then stop and write the result here. A run that fails for a
platform reason is re-dispatched once on the same arm.

## Results

The A/B has not run. The v5 live checks (lineage, above) exercised the
`Capability gaps:` line (all zero) and the `Needs a capable workspace` heading
(`None.`). They did not exercise a real gap or an evidence declaration.
