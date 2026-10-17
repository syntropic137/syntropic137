# E1: gpt-6-luna vs gpt-6.1-sol as the codex verifier (preregistered 2026-10-17)

Status: PROPOSED, DEFERRED until Codex weekly quota resets (11% on
2026-10-17; GPT verify runs are scarce). Nothing dispatched.

## Expected cost

29 train cases x 2 arms = 58 Codex executions.
- Sol arm: 29 x ~$1.0-1.7 = ~$30-50 (production verify median is $1.73).
- Luna arm: 29 x ~$0.05-0.10 = ~$2-3, at 1/20 the price per token, if token
  counts are similar.
- The real cost is Codex quota, not dollars. That is why this is deferred.
  Cheaper fallback: run Sol on a stratified 10-case subset first.

## Question

Can gpt-6-luna replace gpt-6.1-sol in verify without missing more defects?
gpt-6-luna is 20x cheaper per token ($0.10/$0.50 vs $2/$10).

## Arms (one variable: the verifier model)

- Control: `eval-verify-pinned-codex-v1` (codex, `gpt-sol` resolving to gpt-6.1-sol).
- Treatment: `eval-verify-pinned-codex-gpt-6-luna-v1` (codex, gpt-6-luna).
- Held constant: the suite (verifier-seed-v1 v8), the prompt, the phase,
  the codex sandbox and the workspace image.

## Sample

verifier-seed-v1 v8, `--split train`. Every case runs in both arms, so the
comparison is paired. The holdout is not run.

## Hypotheses (all legitimate outcomes)

- H0 (no difference): Luna catches about the same defects as Sol. ADOPT
  becomes a candidate.
- H1 (worse): Luna misses defects that Sol catches. REJECT.
- H2 (better or equal on recall, more false blocks): REJECT for verify, keep
  as a triage pre-filter candidate.

## Metrics

- Primary: catches (blocked AND keyword-judge match) per paired case. The
  keyword judge only, because the LLM judge is pinned to a pre-5 model.
- Guard: false blocks on clean controls. A control both arms block is
  investigated, not scored (suite README).
- Secondary: cost per run, verify duration.

## Mechanism check

Every run's `phases[].model` must read `gpt-6.1-sol` or `gpt-6-luna` as the
arm requires. A run that resolved to anything else is excluded and re-run once.

## Decision rule

Count discordant pairs: cases Sol caught and Luna missed (b) vs Luna caught
and Sol missed (c).
- ADOPT candidate: b - c <= 1 AND Luna has no more false blocks than Sol.
  Then a holdout run decides.
- REJECT: b - c >= 3, or Luna false-blocks a control Sol certified.
- Otherwise INCONCLUSIVE. Report it as inconclusive; do not extend n to chase
  a result.

## Stop rule

Stop when every train case has one scored run per arm. A platform failure is
re-dispatched once, then the pair is excluded. Stop immediately if the Codex
weekly quota on the VPS account drops below 20%.

## Limits

- n is small. This is a screen, not proof of non-inferiority. ADOPT needs the
  holdout plus a production canary.
- Run budget: at most 2 of my runs in flight. Each case is one execution.

## Results

(not yet run)
