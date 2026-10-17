# E2: Sonnet 5.5 vs Opus 5.5 as implementer (preregistered 2026-10-17)

Status: APPROVED by the orchestrator on 2026-10-17, with conditions. Wait for
"GO" after the pit stop, which happens after the orchestrator registers both
new workflows. Nothing dispatched.

Conditions:
- The treatment pins the explicit id `claude-sonnet-5-5`, not the alias.
- **Abort rule:** on the FIRST treatment execution, `phases[].model` must read
  `claude-sonnet-5-5`, and on the FIRST control execution it must read
  `claude-opus-5-5`. The control runs the `opus` alias, installed from main
  by the orchestrator. If either check fails, abort the whole experiment.
- Scoring runs on the platform via `eval-implement-score-v1`
  (`workflows/evals/implement-score/`). That workflow is identical for both
  arms, pinned to `claude-opus-5-5`, and does no judging: the verdict is
  `eval_implementer.py`'s exit code.
- Scoring runs count toward the cap of 2 in flight.

## Question

Does claude-sonnet-5-5 make the hidden tests of real fixes pass as often as
claude-opus-5-5? Implement and fix are 44% of implement-workflow spend, and
Sonnet is half Opus's price per token.

## Arms (one variable: the implement model)

- Control: `eval-implement-pinned-v1` (claude, `opus` resolving to claude-opus-5-5).
- Treatment: a new workflow id, `eval-implement-pinned-sonnet-v1`. It is the
  control file with only `model: sonnet` changed. It must be added and
  registered first; the control is not edited.
- Held constant: the cases, the issue text, the prompt, the tools and the image.

## Sample

implementer-seed-v1, all 5 cases, 2 runs per case per arm: 20 executions in
all. Two runs per case, because one run per case cannot separate the model
from run-to-run noise.

## Hypotheses

- H0: equal pass rate. Sonnet becomes the fix-phase candidate for E3.
- H1: Sonnet passes fewer. Opus stays on implement and fix.
- H2: Sonnet passes more or equal at much lower cost. E3 proceeds, and
  implement itself becomes a later candidate.

## Metrics

- Primary: PASS count from `scripts/eval_implementer.py score` (hidden tests).
- Guard: patch size and files touched outside the fix's files (a scope check).
- Secondary: cost and duration.

## Mechanism check

`phases[].model` must read `claude-sonnet-5-5`. A run on Sonnet 5 is excluded,
because the pinned CLI is known to resolve `sonnet` to Sonnet 5. A leak check
per the suite README is also required.

## Decision rule

- Sonnet PASS >= Opus PASS - 1 (out of 10): proceed to E3.
- Sonnet PASS <= Opus PASS - 3: stop; Opus stays.
- Anything in between: INCONCLUSIVE; do not proceed to E3.

## Stop rule

20 scored executions, or the Claude weekly quota for the VPS account below
20%. A platform failure is re-run once.

## Expected cost (API-equivalent, Claude quota only, no Codex)

Estimated from the median production implement phase ($1.92, 43 min, n=25).
- Opus arm: 10 x ~$1.9 = ~$19.
- Sonnet arm: 10 x ~$1.0 = ~$10, assuming similar token counts at half the
  price per token.
- Scoring: 20 x `eval-implement-score-v1` at roughly $0.3-0.5 each = ~$6-10.
- Total ~$40, across 40 executions. With 2 in flight, about 6-8 h of wall
  clock.

## Protocol deviation 1 (2026-10-17): pilot, then v2 arms

Pair 1 ran on the v1 arms: `exec-18716bf21197` (treatment) and
`exec-b67322b616ca` (control), case `codex-sandbox-tmpdir`.

The v1 prompt (shared, from main) leaves the change uncommitted. The
phase-end lost-work guard therefore fails the phase as a platform failure,
collects no artifacts, and quarantines the dirty tree to
`refs/syn/lost/<exec>/implement` on origin.

Re-dispatching would fail the same way, so the orchestrator decided:

- **Pair 1 is a PILOT and does not count toward the 20.** It may be scored
  from its quarantine ref: the patch is `git diff <pin> <ref>`, the ref's
  parent was checked to equal the pin, and the patch was checked to contain
  no `artifacts/` path. Its score is reported as pilot only.
- The counted runs use new ids, `eval-implement-pinned-v2` (claude-opus-5-5)
  and `eval-implement-pinned-sonnet-v2` (claude-sonnet-5-5). Their prompts are
  byte-identical. They add one step: after writing the patch, reset the tree
  to the pin (`git reset --hard`, `git clean -fd`) and check that
  `git status --porcelain` is empty. v1 is unchanged.
- Counting restarts at 0. The abort rule applies again to the first v2
  execution of each arm.
- Both arms now pin an explicit model id, so the abort rule reads the same
  for both.
- Why not salvage every run: each one would be a "failed (platform)"
  execution with no artifacts. That pollutes the cost, time and failure
  metrics E2 measures, and pushes a quarantine ref per run to origin, which
  later runs could fetch (#2022).

## Protocol deviation 2 (decided 2026-10-17T19:39:23Z): exclude exec-status-lost

The case `exec-status-lost` cannot be passed without guessing names, so it
measures a guess (#2023). Its hidden test monkeypatches
`exec_status_lost.container_state` and `setup_phase._SETUP_RETRY_BACKOFF_SECONDS`.
Neither name is in the task's interface paragraph, and neither exists at the
pin. A static audit of all 5 cases found no other case with unstated names.

- Decided before any Opus (control) result on that case existed. The only
  run on it was Sonnet v2 rep 1: `exec-1f09efd59354`, scored by
  `exec-e5703ace9a87`, FAIL (`AttributeError: no attribute
  'container_state'`). It is reported as excluded data.
- Counted set: 4 cases x 2 reps x 2 arms = 16 runs, 8 per arm.
- The thresholds stay as preregistered in absolute terms (proceed if Sonnet
  >= Opus - 1, stop if Sonnet <= Opus - 3). **Stated plainly: out of 8 per arm
  instead of 10, the same absolute margins are looser.** A 1-run gap is
  12.5% at n=8 but 10% at n=10.
- Approved by the orchestrator.

## Protocol deviation 3 (decided 2026-10-17T20:05Z): fix the cases (suite v2), supersedes deviation 2

The pilot control (Opus v1, `codex-sandbox-tmpdir`, scored from its
quarantine ref as `exec-8713a31f81ce`) FAILed the same 3 hidden tests as the
Sonnet pilot. Both failed on `assert "Could not destroy workspace" in
caplog.text`, a string that exists only in the fix. An audit of every case
then found unstated exact spellings (names, log text, exception text) in 3
cases: `exec-status-lost`, `codex-sandbox-tmpdir` and `token-mint-retry-5xx`.
The other 2 cases are clean.

- Fix, don't exclude. Approved by the orchestrator.
- implementer-seed bumps to **v2**, adding the observable contract to each
  affected case's interface paragraph. `check` now fails on any unstated
  spelling, so the defect cannot recur (README, #2023). The orchestrator
  re-runs `admit` for the 3 cases on a Docker host before any counted run
  uses them.
- **No counted run existed on the 3 cases when this was decided.** The only
  run on any of them was the excluded Sonnet v1-task run on
  `exec-status-lost`, which stays excluded and reported. Its replacement runs
  under v2.
- `exec-status-lost` returns. The counted set is the full 5 x 2 x 2 = 20 again,
  and the thresholds are back to /10 as originally preregistered. The
  "looser at /8" note in deviation 2 no longer applies.
- The 2 clean cases' task text is byte-identical in v1 and v2, so their runs
  count either way.

## Protocol deviation 4 (2026-10-17): scorer v2 for patch transfer

`exec-0a6c05a3e8f2` refused to score the 68,459 B patch of `exec-b2a635a6a0e9`.
The copy it received was 68,358 B. Exactly the patch's 101 trailing-whitespace
bytes were gone: blank diff context lines are a lone space, and that space was
stripped on the way through the prompt. The sha256 guard worked as designed;
nothing was mis-scored.

`eval-implement-score-v2` takes the patch with each line's trailing whitespace
escaped as `<~WS:...~>` (`s` = space, `t` = tab). It decodes the patch with a
fixed script before the same sha256 check, which runs over the original
bytes. Every patch collected so far round-trips byte-exact through the
encoder and the prompt's decoder.

The scorer is identical for both arms, so this is not an experimental
variable. A transfer ERROR is re-scored once under v2. That re-score is the
preregistered "re-run on ERROR", not a new sample.

## Protocol deviation 5 (decided 2026-10-17T20:23:17Z): pause case, suite v3, then FROZEN

Sonnet's v2 run on `pause-not-blocked-by-queue` (`exec-2d494e06998d`, scored
`exec-ce6dec978a4b`) failed partly on `assert raised.value.unsettled == 1`.
The task introduces `AdmissionDrainTimeoutError` but never says it carries an
`unsettled` count, and `unsettled` existed at the pin only as an unrelated
local variable. `check` did not cover attribute reads.

- Decided before the Opus score on that case (`exec-05965b470433`) was read.
  Approved by the orchestrator.
- Suite **v3** states `AdmissionDrainTimeoutError.unsettled`. `check` now also
  covers attribute reads, matched as an attribute access, a `def` or a
  class-level annotation at the pin, with submodules searched at their
  gitlinks. Over all 5 cases the extended check reports nothing at v3.
- Both pause rep 1 runs on the v2 text are excluded data, symmetric across
  arms. Opus FAILed, Sonnet FAILed; the excluded results are reported below.
  Both arms re-run under v3. No re-admit is needed, because `admit` does not
  read the task text.
- Sonnet's score also failed `test_is_refused_at_its_slot_once_the_pause_has_returned`.
  That is reported as-is: it is a behaviour failure, not a spelling.

**Suite FROZEN at v3 from 2026-10-17T20:46:54Z.** Any case defect found after this point
is reported as-is and analysed as a secondary result. There are no more
suite bumps during E2.

## What a "proceed" means (added with deviation 2)

At n=8 per arm, "proceed" means **no evidence of a large quality drop**. It
does not mean Sonnet is equivalent to Opus. E3's go/no-go is phrased that
way. E3's production guards (reverify block rate and escaped defects over
14 days) are the real safety net, not this screen.

## Procedure

1. Launch the implement run for each case, one per arm, alternating arm order.
   Tag every run `eval-research`, `experiment:e2-implementer-sonnet` and
   `arm:control` or `arm:treatment`.
2. Check the first treatment execution's `phases[].model` (the abort rule).
3. When an implement run completes, launch `eval-implement-score-v1` with
   `task=<case id>` and `implement_execution_id=<id>`. The VPS has no platform
   API access for workspaces (SYN_PLATFORM_ACCESS_ENABLED unset, confirmed by
   the orchestrator on 2026-10-17). So the researcher fetches `implement.patch`
   with `syn137-api` and passes it as `patch`, with its sha256 as
   `patch_sha256`. The scorer refuses (ERROR) a patch whose hash does not match,
   so a transcription error is never scored. An ERROR from a mismatch is
   re-run once.
4. Read `score.md` line 1. Record PASS, FAIL or ERROR per execution in the
   Results table below.
5. Read each PASS run's tool trace for leaks (`git log --all`, `git show`,
   `fetch`, `gh`) before counting it (suite README, "Leakage").

## Dependencies and blockers

- The orchestrator must register `eval-implement-pinned-sonnet-v1` and
  `eval-implement-score-v1` on the VPS after the pit stop.
- The patch reaches the scorer through the prompt, because inputs are only
  substituted into prompt text. The agent writes it back out, and the sha256
  check guards that copy. API inputs have no size limit; a very large patch is
  reported to the orchestrator instead of being sent.

## Limitations

- **The case suite was being debugged during E2.** Five protocol deviations
  were made before the freeze: the v1 to v2 workflows, three case-contract
  fixes (suite v2, v3), and the scorer v2. Each was decided before the
  affected counted results were read, and each applies to both arms equally.
  Still, the instrument changed under the experiment, and the result should
  be read with that in mind.
- n = 10 per arm (5 cases x 2 reps) is a screen. "Proceed" means no evidence
  of a large drop, not equivalence.
- Leakage is not prevented by the platform (suite README). PASS runs get a
  trace check.

## Results

INTERIM (2026-10-17, 17 of 20 counted runs scored). No verdict yet: the
decision rule is applied only when all 20 are scored.

Counted runs: reps v2-1 and v2-2; the pause case only for runs launched after
the v3 freeze (2026-10-17T20:46:54Z); the v1-text exec-status-lost run
(`exec-1f09efd59354`) excluded. Generated from the results ledger by a query,
not by hand.

| Case | Opus 5.5 (control) | Sonnet 5.5 (treatment) |
|---|---|---|
| resolve-full-execution-id | 2/2 | 2/2 |
| pause-not-blocked-by-queue (v3) | 1/1 | 1/1 |
| codex-sandbox-tmpdir | 1/1 | 1/2 |
| exec-status-lost | 0/2 | 0/2 |
| token-mint-retry-5xx | 0/2 | 0/2 |
| **Total** | **4/8** | **4/9** |

Per run (implement exec / scorer exec / verdict):

| Arm | Case | Rep | Implement | Scorer | Verdict |
|---|---|---|---|---|---|
| Opus | codex-sandbox-tmpdir | v2-1 | exec-a63d442dd8ef | exec-be7555d5eb0f | PASS |
| Opus | exec-status-lost | v2-1 | exec-769d7f163b6a | exec-edff12cf4758 | FAIL |
| Opus | exec-status-lost | v2-2 | exec-9a6f228bbb54 | exec-51e42c2d7085 | FAIL |
| Opus | pause-not-blocked-by-queue | v2-1 | exec-64816866c28f | exec-8950aab7d45a | PASS |
| Opus | resolve-full-execution-id | v2-1 | exec-6c2384186af5 | exec-2dcb04b123f8 | PASS |
| Opus | resolve-full-execution-id | v2-2 | exec-86845696a663 | exec-a1a8778df1a3 | PASS |
| Opus | token-mint-retry-5xx | v2-1 | exec-d82694c7cca5 | exec-e737f87a900a | FAIL |
| Opus | token-mint-retry-5xx | v2-2 | exec-f42990ce0507 | exec-e0db41948861 | FAIL |
| Sonnet | codex-sandbox-tmpdir | v2-1 | exec-01123a2ee555 | exec-57d80af0e6ad | PASS |
| Sonnet | codex-sandbox-tmpdir | v2-2 | exec-5986906be65d | exec-94481775e45a | FAIL |
| Sonnet | exec-status-lost | v2-1 | exec-eb69c3bab56c | exec-bd82f35e683e | FAIL |
| Sonnet | exec-status-lost | v2-2 | exec-92c14ba7d405 | exec-0348f2822b19 | FAIL |
| Sonnet | pause-not-blocked-by-queue | v2-1 | exec-b7130ffb9463 | exec-1537051d2f57 | PASS |
| Sonnet | resolve-full-execution-id | v2-1 | exec-54b25138e6f4 | exec-d163ed103e20 | PASS |
| Sonnet | resolve-full-execution-id | v2-2 | exec-94f54073597b | exec-f516239e76e0 | PASS |
| Sonnet | token-mint-retry-5xx | v2-1 | exec-767066cdf832 | exec-00724ea43631 | FAIL |
| Sonnet | token-mint-retry-5xx | v2-2 | exec-192ddf47e5d5 | exec-b72bb6c44cc0 | FAIL |

Pending: Opus codex-sandbox-tmpdir v2-2 (`exec-46764613a7dd`, done, score
queued), Sonnet pause v2-2 (`exec-606db3b2e091`, done, score queued), Opus
pause v2-2 (not launched). All held for the API recreate.

Mechanism check: every counted implement run, and both pending ones, report
the arm's model in `phases[0].model` (claude-opus-5-5 or claude-sonnet-5-5).
None was quarantined.

Implement cost, including the 2 pending runs (execution `total_cost_usd`):
Opus $16.25 over 9 runs (mean $1.81); Sonnet $4.65 over 10 runs (mean
$0.46), about 1/4 of Opus. Mean implement duration: Opus 27.6 min, Sonnet
4.1 min. Most Sonnet runs took 77-178 s; checked against the phase
timestamps and the launch ledger (no queue wait), so these are real
durations, not a reporting fault. The longest Sonnet run is pause v2-2 at
19.6 min.

Positive control: the reference fix of resolve-full-execution-id through
scorer v2 PASSed (`exec-a12312e843d1`), so a FAIL is the patch's, not the
harness's.

Both arms fail exec-status-lost and token-mint-retry-5xx every time. Before
the verdict, those 8 FAILs get a read of the failing tests: a case that no arm
can pass measures the case, not the model (reported as-is; the suite is
frozen).

Excluded (reported, not counted), all FAIL: the 2 v1 pilots, the v1-text
exec-status-lost Sonnet run, and the 2 pre-v3 pause runs.
