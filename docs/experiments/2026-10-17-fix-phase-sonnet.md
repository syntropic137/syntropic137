# E3: Sonnet 5.5 on fix and fix_2 in implement-v4-precheck (preregistered 2026-10-17)

Status: PROPOSED, gated on E2 reaching "proceed". Not approved, nothing dispatched.

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
