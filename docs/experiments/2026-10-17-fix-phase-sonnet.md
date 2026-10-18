# E3: Sonnet 5.5 on fix and fix_2 in implement-v4-precheck (preregistered 2026-10-17)

Status: PROPOSED. The E2 gate is met (2026-10-18: Sonnet 5/10 vs Opus 6/10,
"proceed" on the boundary; see E2 Results). Not yet approved, nothing
dispatched. The orchestrator decides when it runs.

The gate is weak by design. An E2 "proceed" (n=8 per arm) only means no
evidence of a large quality drop on implementation, not equivalence. This
experiment's production guards (reverify block rate, escaped defects over
14 days) are the actual safety net.

## Question

With Opus 5.5 implementing and gpt-6.1-sol verifying, does moving fix and
fix_2 to claude-sonnet-5-5 keep the quality bar, and how much does it save?

## Arms (one variable: the model on fix and fix_2)

- Control: `sdlc-implement-v4-precheck` (fix and fix_2 on Opus 5.5).
- Treatment: a new workflow id, `sdlc-implement-v4-precheck-sonnet-fix`. It is
  identical except fix and fix_2 use `sonnet`.
- Held constant: premise, implement, verify, reverify, finalize, all prompts
  and the verifier model.

## Sample

Real backlog tasks assigned alternately, as in the v4-precheck A/B. n = 6 per
arm, so 12 runs in all. These are production runs, so the orchestrator assigns
them, not me (my cap is 2 runs).

## Expected cost

These are production tasks that run anyway, so the experiment adds about $0.
Per run, fix plus fix_2 is about $2.6 on Opus (production medians $1.66 +
$0.98). The expected treatment saving is ~$1.3 per run, ~$8 across 6 runs.
Codex use is the same in both arms (verify and reverify are unchanged).

## Metrics

- Primary: escaped defects per merged PR over a 14-day window after merge.
- Guard: the reverify block rate after fix. If Sonnet's fixes fail reverify
  more often, the extra rounds can cost more than the model saves.
- Secondary: fix plus fix_2 cost, rounds to READY, time to READY.

## Decision rule

- ADOPT: escaped defects in the treatment arm do not exceed control, AND
  rounds to READY do not exceed control + 1, AND fix cost is at least 30% lower.
- REJECT: any treatment escape that the control's pattern would not have
  produced, or rounds +2.
- Otherwise INCONCLUSIVE.

## Stop rule

12 runs merged or closed, then the 14-day window. Stop early on any escaped
defect traced to a Sonnet fix.

## Limits

n = 6 per arm cannot detect small differences in escape rate. This is a
canary, not proof.

## Results

(not yet run)
