# E1: gpt-6-luna vs gpt-6.1-sol as the codex verifier (preregistered 2026-10-17)

Status: COMPLETE 2026-10-18. Verdict: REJECT gpt-6-luna for verify, on both
triggers (b - c = 6; Luna false-blocked a clean control Sol certified). See
Results. gpt-6.1-sol stays the verifier.

## Amendment 1 (2026-10-17T21:02:48Z): treatment arm is gpt-5.6-luna

Recorded before any gpt-5.6-luna result existed. Approved by the orchestrator.

- gpt-6-luna could not run on the VPS. Both the launch `exec-e74804add4aa`
  and its one preregistered re-dispatch `exec-d19e857406a3` failed in ~50 s
  with `codex reported: workspace routing discovery unauthorized (401)`,
  classified as a platform failure, at $0. The Sol arm's first run
  (`exec-9c8b76116c6b`) completed on the same case and image 13 min earlier.
- The orchestrator found that gpt-6-luna does answer through the owner's local
  Codex CLI. So the 401 is specific to the VPS Codex credential (hypothesis;
  raised with the owner). Both launches are excluded as platform failures.
  They stay in `launches.jsonl`, and `score` ignores failed runs.
- The treatment arm is now `eval-verify-pinned-codex-gpt-5-6-luna-v1` (codex,
  `gpt-5.6-luna`, $0.20/$1.20 per MTok, about 1/10 of Sol). Checked on
  2026-10-17: the server definition matches the repo, `phases/verify.md` is
  byte-identical to the control's, and the sandbox is `workspace-write`. Its
  first launch doubles as the availability probe and the arm's abort check.
  If it fails on the platform, E1 stops.
- Everything else is unchanged: design, cases, decision rule, stop rule.
  Expected Luna-arm cost is now ~$3-6.
- If the VPS auth is fixed, gpt-6-luna may run later as a third arm against
  the same Sol runs. That would be a separate, later amendment.

## Amendment 2 (2026-10-17): E1 stopped on a VPS Codex outage, not on the cheap models

The amendment 1 probe on gpt-5.6-luna (`exec-16537ad92479`) failed with the
same 401. No codex phase on any model succeeded on the VPS after 20:49:03Z.
The orchestrator's gpt-5.6-sol smoke run (`exec-328962e4fafb`) then failed
the same way, while `/health` still reported the credential as valid. So all
three "Luna" failures were a credential outage starting around 20:50Z, not
the models being unavailable. Amendment 1's hypothesis (that the credential
cannot route non-Sol models) is withdrawn.

- E1 is stopped until the orchestrator confirms the re-auth.
- On resume, both cheap arms (gpt-6-luna, gpt-5.6-luna) are re-probed. The
  original treatment, gpt-6-luna, comes back if it runs, and the arm choice
  is recorded before any treatment result is read.
- The one valid run so far is the Sol control on `binary-artifact-minio-key`
  (`exec-9c8b76116c6b`). It stands.

## Amendment 3 (2026-10-18, recorded before any treatment verdict was read): treatment is gpt-6-luna again

After the VPS Codex re-auth, the re-probe `exec-bce939a02c54`
(`eval-verify-pinned-codex-gpt-6-luna-v1`, on `binary-artifact-minio-key`)
completed, and `phases[].model` reads `gpt-6-luna`. So the original
preregistered treatment runs, and amendment 1's switch to gpt-5.6-luna is
reversed. gpt-5.6-luna was not probed: it would only be needed if gpt-6-luna
failed, and it is not a third arm.

- The probe is the treatment arm's first run on that case, and its abort
  check. It passed the abort check, and it counts as that case's treatment
  run.
- Recorded before its report or verdict was read.
- Everything else is as in the final preregistration: 29 train cases x 2
  arms, decision rule on b - c, stop rule, keyword judge.
- Concurrency: the platform cap is 2 in flight, shared with E3.

## Question

Can gpt-6-luna replace gpt-6.1-sol in verify without missing more defects?
gpt-6-luna is 20x cheaper per token ($0.10/$0.50 vs $2/$10 per MTok).
verify, reverify and reverify_2 are 35% of implement-workflow spend, and
verify takes a median of 37 min (research doc, section 1).

## Arms (one variable: the verifier model)

- Control: `eval-verify-pinned-codex-v1`, codex, `gpt-sol`. The platform
  rewrites this alias itself to gpt-6.1-sol.
- Treatment: `eval-verify-pinned-codex-gpt-6-luna-v1`, codex, `gpt-6-luna`.
- Checked 2026-10-17: `phases/verify.md` is byte-identical across the arms,
  and the YAMLs differ only in id, name, description and model. Both use
  `sandbox: workspace-write`.
- Held constant: suite verifier-seed-v1 v8, the cases, the pins, the prompt,
  the image, and the keyword judge.

## Sample

verifier-seed-v1 v8, `--split train`: 26 defect cases and 3 clean controls,
29 cases. Every case runs once in each arm: **58 executions**. The comparison
is paired by case. The holdout (10 defects, 1 control) is not run; it is kept
for the confirmation step an ADOPT would need.

## Expected cost

| Arm | Runs | Per run | Total |
|---|---|---|---|
| gpt-6.1-sol | 29 | ~$1.0-1.7 (production verify median $1.73; eval verify runs are shorter) | ~$30-50 |
| gpt-6-luna | 29 | ~$0.05-0.10, if token counts are similar at 1/20 the price | ~$2-3 |
| Total | 58 | | **~$32-53 of Codex quota, $0 Claude** |

Wall clock: about 5-10 min per run. With E2 sharing the 2-slot cap, plan on
4-8 h. The orchestrator schedules it.

## Hypotheses (all legitimate outcomes)

- H0: Luna catches about the same defects as Sol. ADOPT becomes a candidate.
- H1: Luna misses defects that Sol catches. REJECT.
- H2: Luna's recall is equal or better, but it false-blocks more. REJECT for
  verify; Luna stays a candidate as a triage pre-filter.

## Metrics

- Primary: caught = blocked AND keyword-judge match, per paired case. Keyword
  judge only: the LLM judge is pinned to a pre-5 model (#2021).
- Guard: false blocks on the 3 clean controls. A control both arms block is
  investigated against the code before scoring (suite README), not counted as
  a false block.
- Secondary: cost and verify duration per run, and the cost per true catch.

## Mechanism check (abort rule)

On the first execution of each arm, `phases[].model` must read
`gpt-6.1-sol` (control) or `gpt-6-luna` (treatment). If either does not,
abort. After that, check every run: a run on any other model is excluded and
re-run once.

## Launch

`eval_suite.py launch` starts every case at once. That breaks the 2-in-flight
cap, so it is not used. A wrapper launches one case at a time with the
script's own functions: `stable_eval`, the same `/workflows/{id}/execute`
body, and `_append_launch` to the suite's `launches.jsonl`. So
`eval_suite.py score --workflow <id> --split train` reads the runs unchanged.
Every run is also tagged `eval-research`, `experiment:e1-verifier-luna` and
`arm:<control|treatment>`. Arms alternate case by case.

## Decision rule

Count the discordant pairs: b = Sol caught and Luna missed, c = Luna caught
and Sol missed.

- ADOPT candidate: b - c <= 1 AND Luna has no more false blocks than Sol.
  Then a holdout run (11 cases x 2 arms) decides, and after that a production
  canary on reverify, where Luna would replace Sol on the round where most
  defects are already fixed.
- REJECT: b - c >= 3, or Luna false-blocks a control Sol certified.
- Otherwise INCONCLUSIVE. Report it as inconclusive; do not extend n.

As with E2: with n=26 defects, ADOPT means "no evidence of a large recall
drop", not equivalence.

## Stop rule

Stop when every train case has one scored run per arm. A platform failure is
re-dispatched once, then the pair is excluded. Stop immediately and tell the
orchestrator if the Codex weekly quota on the VPS account falls below 20%, or
a run fails on a usage limit.

## Limits

- Only 3 clean controls, so the false-block guard is weak. It can catch a
  verifier that blocks everything, not a modest rise in false positives.
- gpt-6.1-sol has never been scored on verifier-seed-v1. The control arm is
  also the first real baseline for our production verifier, and is worth
  having even if Luna is rejected.

## Results (2026-10-18)

All 29 train cases have one scored run per arm (58 runs; no platform
failures, no exclusions). Every run passed the mechanism check
(`phases[].model` read `gpt-6.1-sol` or `gpt-6-luna`).

### Verdict: REJECT gpt-6-luna for verify

Both REJECT triggers fired:

1. b - c = 9 - 3 = 6 (bar: >= 3).
2. Luna false-blocked `clean-fitness-stale-waivers`, which Sol certified.
   Checked against the code: a false positive (below).

H2's fallback (Luna as a triage pre-filter) is also not supported. On
verdict alone, ignoring the keyword judge, Luna certified 5 of 26 defect
cases (fence-bound-fails-on-real-postgres, live-commits-unvalidated-sha,
shared-esp-stream, input-alias-independent-resolution,
workflow-run-task-undeliverable). Sol blocked all 26. A pre-filter whose
"certified" lets 1 in 5 known defects through cannot skip the real verifier.

### Defect cases (n = 26)

| | Sol caught | Sol missed |
|---|---|---|
| Luna caught | 9 | 3 (c) |
| Luna missed | 9 (b) | 5 |

- Sol 18/26, Luna 12/26.
- b (Sol only): broker-deny-path-untested, event-schema-gate-ignores-identity,
  execution-id-as-eval-id, fence-bound-fails-on-real-postgres,
  live-commits-unvalidated-sha, redis-url-password-logged,
  sessions-execution-filter-dropped, shared-esp-stream,
  token-injector-get-post-only.
- c (Luna only): guard-moved-gitlink-unsaved-work,
  start-clock-read-before-settle, transcript-superseded-revision-issues.
- Both missed: input-alias-independent-resolution, pit-stop-password-on-argv,
  shared-body-expired-by-oldest-capture, workflow-run-inputs-go-nowhere,
  workflow-run-task-undeliverable. Sol blocked all 5 but the keyword judge did
  not match. These are follow-ups for a case or judge review, not counted
  here.

### Clean controls (n = 3)

| Case | Sol | Luna | Checked against the code |
|---|---|---|---|
| clean-api-shape-silent-absence | blocked | certified | Sol right: 2 real bugs, still on main, filed as #2030. The control is not clean |
| clean-fitness-stale-waivers | certified | blocked | Luna false positive: claimed the APS submodule was absent. It was present; Luna's `find \| head -50` truncated before it |
| clean-list-endpoints-model-defaults | blocked | certified | Sol false positive: `requires_repos` defaulting to True matches the domain default; every writer sets it |

Deviation, recorded after results: clean-api-shape-silent-absence is
retired as a control (suite README rule for blocked controls). A defect case
at the same pin can follow once #2030 is fixed. It changes no verdict: as
scored, Sol has 2 false blocks and Luna 1, but trigger 2 needs only that Luna
blocked a control Sol certified, and the code confirms that control is clean.
After the check, each arm has 1 false positive, and Luna also certified a
real bug.

### Cost and time

| | Sol (control) | Luna (treatment) |
|---|---|---|
| Total, 29 runs | $6.74 | $0.36 |
| Mean per run | $0.233 | $0.0125 |
| Per true catch | $0.37 | $0.03 |
| Mean duration (28 looped runs) | 2.1 min | 0.9 min |

Luna is ~19x cheaper per run. That is not worth 6 net missed defects in 26
at the verify gate, where one escape costs more than the whole suite.

### Per-run record

| Case | Sol | Luna | Sol exec | Luna exec |
|---|---|---|---|---|
| binary-artifact-minio-key | PASS blocked | PASS blocked | exec-9c8b76116c6b | exec-bce939a02c54 |
| broker-deny-path-untested | PASS blocked | FAIL blocked | exec-143715589b19 | exec-6326194ef3a8 |
| clean-api-shape-silent-absence | FAIL blocked | PASS certified | exec-bb6cf3fd139a | exec-1b7fb23a8eae |
| clean-fitness-stale-waivers | PASS certified | FAIL blocked | exec-44194843a292 | exec-f9a95891f401 |
| clean-list-endpoints-model-defaults | FAIL blocked | PASS certified | exec-81f95bae92e2 | exec-2f734df73d69 |
| cli-packages-own-remote-check | PASS blocked | PASS blocked | exec-44d026f6735d | exec-213e13a72932 |
| codex-cost-limit | PASS blocked | PASS blocked | exec-5f5c4c54e62b | exec-8bec5b5ddfce |
| event-schema-gate-ignores-identity | PASS blocked | FAIL blocked | exec-97d5ae886c19 | exec-a515651f1e4c |
| execution-id-as-eval-id | PASS blocked | FAIL blocked | exec-ad5dd30f36e4 | exec-672a317a8e17 |
| executions-total-is-page-length | PASS blocked | PASS blocked | exec-f038eeb1f1bf | exec-da2e40949644 |
| fence-bound-fails-on-real-postgres | PASS blocked | FAIL certified | exec-d9b6a8c721da | exec-13b4031dca79 |
| github-shorthand-any-slash | PASS blocked | PASS blocked | exec-12b156adb996 | exec-1ab9bb2126ec |
| guard-moved-gitlink-unsaved-work | FAIL blocked | PASS blocked | exec-b420a2027873 | exec-041bb1cd020e |
| heatmap-test-reads-clock-repeatedly | PASS blocked | PASS blocked | exec-a57c1a8c68d3 | exec-9b9ae6b3e7a2 |
| input-alias-independent-resolution | FAIL blocked | FAIL certified | exec-45b6def59ec5 | exec-75f146b14519 |
| live-commits-unvalidated-sha | PASS blocked | FAIL certified | exec-e09d6ea082db | exec-f0735b6894f4 |
| pit-stop-password-on-argv | FAIL blocked | FAIL blocked | exec-fd1558a30b08 | exec-640141205fcb |
| prompt-claims-checkout-without-clone | PASS blocked | PASS blocked | exec-cf12403e3d37 | exec-6282ee08fcdb |
| redis-retry-non-idempotent | PASS blocked | PASS blocked | exec-c0399e8b72dd | exec-ed21892208c9 |
| redis-url-password-logged | PASS blocked | FAIL blocked | exec-bb5df51f8aef | exec-9f31af3cae53 |
| repo-privacy-ignores-app | PASS blocked | PASS blocked | exec-8709d0a97044 | exec-f4107b59169c |
| sessions-execution-filter-dropped | PASS blocked | FAIL blocked | exec-c5a7e943c6ea | exec-5f797bfcb08a |
| shared-body-expired-by-oldest-capture | FAIL blocked | FAIL blocked | exec-bfd1e7e69ed4 | exec-39f0b763df45 |
| shared-esp-stream | PASS blocked | FAIL certified | exec-89cff6882d96 | exec-19e60c131a4d |
| start-clock-read-before-settle | FAIL blocked | PASS blocked | exec-75c2cc877e66 | exec-d33524905a0d |
| token-injector-get-post-only | PASS blocked | FAIL blocked | exec-44a5ab947873 | exec-8ca7cd051354 |
| transcript-superseded-revision-issues | FAIL blocked | PASS blocked | exec-be08605a467a | exec-df3dd8ee3005 |
| workflow-run-inputs-go-nowhere | FAIL blocked | FAIL blocked | exec-1c049cdc5db7 | exec-0e95c6526e20 |
| workflow-run-task-undeliverable | FAIL blocked | FAIL certified | exec-6f48e30f67e9 | exec-8eca9380dbed |
