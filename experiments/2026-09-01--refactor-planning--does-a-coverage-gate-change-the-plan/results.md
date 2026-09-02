# Results

Six runs, three targets, one variable. Artifacts in `runs/`, pulled from the
deployment after the fact; `runs/<RUN>_<phase>.json` is the phase artifact and
`runs/<RUN>.json` the execution record.

## Headline

| # | Prediction | Observed | Score |
|---|---|---|---|
| P1 | v3 runs NO coverage command (0/3) | 0/3 — no coverage command, no coverage output in any A research artifact | correct |
| P2 | gated arm runs a real coverage command (3/3) | 3/3 — real invocations with real output | correct |
| P3 | gated arm returns CHARACTERIZATION TESTS REQUIRED FIRST on >=2/3 | 2/3 (B1, B3). B2 returned SAFE TO REFACTOR on measured 96% coverage | correct |
| P4a | v3 leads with a module split (3/3) | 3/3 | correct |
| P4b | gated arm leads with test work (>=2/3) | 1/3 clearly (B2). B1 opens with a decomposition section before its test spec | **partial** |
| P5 | gated arm costs 1.2x-1.8x the $5.83 baseline | unscorable — 3 runs failed, 3 cancelled | **inconclusive** |
| P6 | v3's cross-model-review executes on CLAUDE (3/3) | 3/3 — all three died on claude's own error text | correct |

## The finding that was not predicted

The strongest signal is not in any prediction. It is a word count.

| run | "characterization" | "coverage" |
|---|---|---|
| A1 (no gate) | 0 | 0 |
| A2 (no gate) | 0 | 0 |
| A3 (no gate) | 0 | 5 |
| B1 (gated) | 18 | - |
| B2 (gated) | 19 | - |

Two of three ungated plans never use either word once, across documents of
18-27KB. A1's first ordered step is `wc -l` on the new module — it verifies the
FILE GOT SMALLER, with no test anywhere in the sequence.

So the gate does not merely add a phase that reports coverage. It changes what
the plan is about. Without it, "refactor this 1582-line module" is understood as
a file-size problem; with it, as a behaviour-preservation problem. That is a
difference in kind, and it is what the probe was actually asking.

## P6, and why the evidence is admissible

The eval pack ruled `cost_by_model` inadmissible for P6 because it records the
DECLARED model and reports `gpt-5.6-sol` whichever binary ran. The runs
supplied better evidence than the transcript inspection anticipated — they
failed, with claude's own error text:

```
Agent failed: There's an issue with the selected model (gpt-5.6-sol). It may not
exist or you may not have access to it. Run --model to pick a different model.
(phase=cross-model-review, exit_code=1) (tokens=0+0)
```

Codex does not say "Run --model to pick a different model" about its own model
id. The phase ran on claude. Confirmed 3/3 in-pack, plus the excluded
pre-hypothesis run.

## The control

`B2`'s `cross-model-review` COMPLETED on codex. Same phase, same model id, same
deployment — on a workflow freshly installed rather than round-tripped through
the lossy exporter, which preserved `provider: codex`. That is the clean
counterpart to P6: the failure is the missing provider, not the model id.

## Cost

$19.83 across six runs. P5 is unscorable rather than merely uncertain: the A arm
died at phase 3 of 4 and the B arm was cancelled at phases 3-5 of 5, so neither
completed a run to compare against five complete baselines.
