# E3: Sonnet 5.5 on fix and fix_2 in implement-v4-precheck (preregistered 2026-10-17)

Status: PROPOSED. The E2 gate is met (2026-10-18: Sonnet 5/10 vs Opus 6/10,
"proceed" on the boundary; see E2 Results). Not yet approved, nothing
dispatched. The orchestrator decides when it runs.

The gate is weak by design. An E2 "proceed" (n=8 per arm) only means no
evidence of a large quality drop on implementation, not equivalence. This
experiment's production guards (reverify block rate, escaped defects over
14 days) are the actual safety net.

## Amendment 1 (2026-10-18, before any run): explicit model id

The treatment pins `claude-sonnet-5-5`, not the `sonnet` alias. The CLI may
resolve that alias to an older Sonnet, which is the same condition E2 used.
The workflow is `workflows/sdlc/implement-v4-precheck-sonnet-fix/`. It is a
copy of the control: `diff` shows only id, name, description and the two
fix-phase model lines. The mechanism check: on the first treatment run,
`phases[]` for fix (and fix_2, if it runs) must read `claude-sonnet-5-5`, and
every other phase must match the control. If not, abort.

## Amendment 2 (2026-10-18, before any treatment run): task list and a fix-never-ran outcome

The orchestrator assigned 12 backlog issues in syntropic137/syntropic137,
alternating control/treatment, launched in this order:

| # | Arm | Issue |
|---|---|---|
| 01 | control | #1949 |
| 02 | treatment | #1878 |
| 03 | control | #1563 |
| 04 | treatment | #1632 |
| 05 | control | #1433 |
| 06 | treatment | #1455 |
| 07 | control | #1420 |
| 08 | treatment | #1144 |
| 09 | control | #1470 |
| 10 | treatment | #1125 |
| 11 | control | #1055 |
| 12 | treatment | #1182 |

Before any treatment run, 5 of the first-draft tasks were swapped because a
workspace agent could not reach a real fix round on them. 4 of those 5 were in
the treatment arm, which would have biased the experiment against Sonnet:

| Slot | Retired | Why |
|---|---|---|
| 04 T | #1502 | its own release and VPS gate was likely unmet |
| 06 T | #1302 | a design call |
| 09 C | #1267 | held for a pending experiment |
| 10 T | #1242 | `.github/workflows` only, which the App token cannot write |
| 12 T | #1389 | submodule changes |

The orchestrator picked the replacements; the retired briefs are kept beside
the live ones.

New outcome: **fix phase never ran**. A run whose verify certifies the first
implementation, or that ends before fix, says nothing about the fix model. It
is reported per run, and that pair does not count toward ADOPT or REJECT, so
the effective n per arm may be below 6. Each run's brief is the issue text
plus the same trap list. Runs are tagged `eval-research`,
`experiment:e3-fix-sonnet`, `arm:<arm>` and `issue:<n>`. At most 1 E3 run is
in flight; the platform total stays at 2.

## Amendment 3 (2026-10-18, after run 02, before run 03): fix timed out in gates

Approved by the orchestrator. Run 02 (treatment, #1878, exec-14a4ac5ee881)
passed the mechanism check (fix on `claude-sonnet-5-5`, every other phase
matching the control). Sonnet pushed its fix within about 3 minutes. The
phase then hit its 60-minute limit (exit 124) while the verification gates
ran in series: `just preflight-agent` (~19 min) then `uv run pytest -m unit`
(at 65% when killed). The chain had been restarted from scratch for a
one-line lint fix. No reverify ran.

- New outcome: **fix ran; phase timed out in gates; no reverify**. It counts
  as a failed round for rounds and time to READY. It is neither an escape nor
  "fix phase never ran".
- #1878 is not re-dispatched (it has PR #2031). The orchestrator's
  independent reverify of #2031 stands in as its reverify verdict.
- Every run's outcome is tagged with whether a gate wait or timeout happened,
  and whether the agent restarted a gate chain. This lets the arms be
  compared on gate hangs separately from the model's own work. The gate time
  itself is logged as a platform papercut.

## Amendment 4 (2026-10-18, before run 04's result): replacement control

Run 03 (control, #1563, exec-6bd2b6ff9fbf) ended as a correct refusal: the
issue was already fixed on main (#1611, #1709), and the orchestrator closed
it. Its outcome is "fix phase never ran". The orchestrator added a replacement
control, run 13, which runs after run 12: #2030, the api_shape.py bug that E1's
Sol arm found. Its brief's traps section is identical to the other 12 briefs.

The PC-212 advice ("re-run only the failing gate") is deliberately left out of
every brief, so the arms stay comparable. It is a candidate for a later
one-variable prompt A/B.

## Amendment 5 (2026-10-18, run 06 in flight): two more controls and a stale-issue pre-check

Run 05 (control, #1433, exec-785b58e5cb77) was also a correct refusal: the
premise is false on main ddfa33d3f. The orchestrator re-scoped #1433. That
leaves the control arm with 0 countable runs out of 3. The cause is stale
backlog issues; implement is Opus in both arms, so the fix model is not
involved.

- Two controls are added after run 13, with traps sections byte-identical to
  the other briefs:
  - 14, #1961 (`debounce_seconds` never applied). Pre-checked on main.
  - 15, #1989 (order-dependent unit failures). Not pre-checked; a refusal
    there is a task-validity outcome.
- Pre-check, applied to both arms: before a brief launches, a read-only check
  of origin/main (about a minute) looks for the defect the issue names. If
  the defect is gone, the brief is skipped and reported, not run. A skipped
  brief is neither a run nor a pair.

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
