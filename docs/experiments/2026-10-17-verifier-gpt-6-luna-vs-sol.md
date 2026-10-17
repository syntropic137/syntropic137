# E1: gpt-6-luna vs gpt-6.1-sol as the codex verifier (preregistered 2026-10-17)

Status: FINAL PREREGISTRATION, sent to the orchestrator for scheduling. It
runs after E2's held cases are running. The Codex quota is no longer the
blocker (weekly 99% on 2026-10-17, after the owner's plan upgrade). Nothing
dispatched.

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

## Results

(not yet run)
