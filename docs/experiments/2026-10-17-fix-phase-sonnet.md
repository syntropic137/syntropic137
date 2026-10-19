# E3: Sonnet 5.5 on fix and fix_2 in implement-v4-precheck (preregistered 2026-10-17)

Status: ALL RUNS DONE 2026-10-19. Interim verdict ADOPT (provisional): rounds
and cost clauses met; escapes 0 so far, final after the windows close
2026-11-02. Control n = 2, below the preregistered 6. See Results.

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

## Amendment 6 (2026-10-18, run 06 in flight): two briefs swapped after the pre-check

The orchestrator swapped two briefs. The replacements' traps sections are
byte-identical to the others, and both defects are present on origin/main.

| Slot | Retired | Why | Replacement | Pre-check |
|---|---|---|---|---|
| 08 T | #1144 | mostly fixed by de65d65ab | #2028, reverify fix phases delete `.mutations/` | no `.mutations` rule in `workflows/sdlc/reverify-pr` |
| 09 C | #1470 | reproduces only on macOS | #2021, the eval judge is pinned to a pre-5 model | `scripts/eval_suite.py:987` |

The other briefs from 07 to 15 passed the pre-check. 07, 10, 11, 12 and 14
are present. 15 (#1989) is unclear, because order dependence needs a test
run.

## Amendment 7 (2026-10-18, run 06 in flight): up to 2 E3 runs at once, and attribution of post-certification defects

- The orchestrator allowed run 07 to start while run 06 was still running.
  The platform total stays at 2, including the orchestrator's independent
  reverify. Concurrency is not the variable under test and affects both arms
  the same way.
- A defect that the independent reverify finds after the in-run
  certification is attributed to the phase whose commit introduced it. To
  find that phase, the implement head is diffed against the fix head. Only a
  defect introduced or reintroduced by a fix-phase commit counts against the
  fix model. A defect present since implement that the fix did not close is
  recorded as "fix left an implement defect open", in both arms alike.
  - Run 04 (#2032) is the first example. Independent reverify
    exec-c4e36047a35d blocked two problems: index-flagged files, and a failed
    `git status` read as clean. Both were already in implement 2b38a58a's
    `[ -z "$(git status --porcelain)" ]`. The Sonnet fix 6e45b105 widened the
    flags but closed neither, and the in-run reverify missed both.

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

## Results (interim, 2026-10-19; final after the escape windows close 2026-11-02)

All 15 briefs ran. The interim verdict is **ADOPT, provisionally**: Sonnet 5.5 on fix
meets the rounds and cost clauses, and no escape has been found so far. The escape
clause cannot be settled until every merged PR's 14-day window closes. The control
arm ended at n = 2 countable pairs, a third of the preregistered 6, so this is a
canary at best.

### What each run did

| Run | Arm | Issue | PR | Fix | Rounds to READY | Fix + fix_2 cost | Run total |
|---|---|---|---|---|---|---|---|
| 01 | C | #1949 | #2029 | never ran (certified first verify) | - | - | - |
| 02 | T | #1878 | #2031 | ran; timed out in gates; no reverify | failed round | $0.28 | $4.52 |
| 03 | C | #1563 | - | never ran (correct refusal: already fixed) | - | - | - |
| 04 | T | #1632 | #2032 | ran | 1 | $0.49 | $4.96 |
| 05 | C | #1433 | - | never ran (correct refusal: premise false) | - | - | - |
| 06 | T | #1455 | #2033 | ran | 1 | $1.02 | $7.61 |
| 07 | C | #1420 | #2034 | ran | 2 | $5.53 | $18.14 |
| 08 | T | #2028 | #2035 | ran | 1 | $0.65 | $8.04 |
| 09 | C | #2021 | #2036 | ran | 1 | $1.16 | $9.55 |
| 10 | T | #1125 | #2037 | ran | 1 | $0.43 | $6.10 |
| 11 | C | #1055 | #2038 | never ran (certified first verify) | - | - | $5.48 |
| 12 | T | #1182 | #2039 | never ran (certified first verify) | - | - | $7.73 |
| 13 | C | #2030 | #2040 | never ran (certified first verify) | - | - | $3.84 |
| 14 | C | #1961 | #2041 | never ran (certified first verify) | - | - | $5.90 |
| 15 | C | #1989 | - | never ran (correct refusal: could not reproduce) | - | - | $1.61 |

Countable pairs: treatment 4 (04, 06, 08, 10), control 2 (07, 09). Run 02 is a
failed treatment round, as amendment 3 defines it.

### Against the decision rule

| Clause | Treatment | Control | Met? |
|---|---|---|---|
| Rounds to READY within control + 1 | mean 1.0 (1.2 counting 02's failed round as a round) | mean 1.5 | yes |
| Fix cost at least 30% lower | mean $0.65 per run; $0.57 per round including 02 | mean $3.35 per run; $2.23 per round | yes, about 70 to 80% lower |
| Escapes not above control | 0 so far | 0 so far | open until 2026-11-02 |

The cost clause holds even against the cheaper control alone (09, $1.16 for one
round). It does not depend on 07's second round.

### Post-certification defects, by the phase that introduced them (amendment 7)

The orchestrator's independent reverify blocked an in-run-certified head in 5 runs.
Each code finding was traced to the commit that introduced it:

| Run | Arm | Finding | Introduced by | Fix commit introduced it? |
|---|---|---|---|---|
| 01 | C | B1, skipped YAML still drove the plugin preflight | implement | n/a (fix never ran) |
| 04 | T | B1 index-flagged files, B2 failed `git status` read as clean | implement 2b38a58a | no: Sonnet fix widened flags, closed neither |
| 06 | T | F1, to-do projection queued work from an unordered start | pre-PR code, untouched by implement | no |
| 07 | C | B1, null summary settled from overwritten session totals | implement ba0aa8ed1 | no: Opus fix and fix_2 left it open |
| 10 | T | R1 platform recipes missing from the dump, R2 interpolations dropped | implement 569139e41 | no: Sonnet fix added only the module check |

Runs 09 and 11 were blocked on evidence only (judge calibration, mutation
evidence), not code. 02, 08, 12 and 13 passed the independent reverify clean.

No defect in either arm was introduced by a fix commit. "Fix left an implement
defect open" happened in 4 of the 6 countable pairs, in both arms (3 T, 1 C). That
is a miss by the in-run gpt-6.1-sol reverify, which is the same in both arms, so it
does not separate them. It is the strongest finding here and belongs in its own
experiment: an in-run reverify that re-reads the whole diff, not only the prior
findings.

### Other findings

- **The fix phase is mostly gate time.** In every fix that ran, the two workspace
  gates took 68 to 98% of the phase (02: timed out at 60 min; 04: ~30 of 41; 06:
  ~40 of 59; 07: ~42 of 51 and ~32 of 36; 08: ~51 of 52; 09: ~40 of 43; 10: ~48 of
  49). The model's own work is a few minutes, so the fix model barely moves time to
  READY. Gate time is PC-212.
- **The fix phase rarely runs.** 8 of 15 briefs never reached fix: 3 correct
  refusals (03, 05, 15) and 5 certified on the first verify (01, 11 to 14). With the premise check and a
  strong implementer, the fix model governs a minority of runs, which is why the
  control arm ran short.
- **Platform issues found:** PC-213 (codex DNS failure, 06), PC-215 (agent 403 on
  integration evidence), PC-216 (resume refused its own earlier push), PC-217
  (shallow-clone mutation run void).

### Still open

- Escape windows: runs 01, 02, 04 and 06 to 2026-11-01; 07, 08 and 10 to 13 to
  2026-11-02. #2036 (09) and #2041 (14) are not merged yet; #2036 waits on a live
  judge calibration that needs the owner's API key.
- The final verdict is written when the windows close. Any escape traced to a Sonnet
  fix commit is an immediate REJECT (stop rule).
