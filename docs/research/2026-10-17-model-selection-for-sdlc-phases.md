# Model selection for SDLC phases (research, 2026-10-17)

Status: first draft. Owner: eval researcher session, reporting to the Syn137
Orchestrator. Experiments that test this doc: `docs/experiments/2026-10-17-*.md`.

## TLDR

- Public evidence ranks Opus 5.5 and Sonnet 5.5 close together for
  implementation, and that evidence comes mostly from vendors. Nothing public
  measures either model as a code **verifier** against real escaped bugs. Our
  own suites are the only evidence that can decide a phase.
- We have almost no measured data of our own. Opus 5.5 caught 4/4 on
  verifier-seed-v1 v1. gpt-6.1-sol was never scored on verifier-seed-v1. The
  Sonnet, Luna and Terra eval workflows have never run. implementer-seed-v1 has
  never run.
- Where the money goes: implement, fix and fix_2 (Opus 5.5) are 51% of
  implement-workflow spend. verify, reverify and reverify_2 (gpt-6.1-sol) are
  35%, and verify takes a median of 37 min.
- The first experiments: a cheaper GPT verifier (E1), Sonnet 5.5 as
  implementer (E2), and Sonnet 5.5 on the fix phases (E3, gated on E2).

## 1. Where cost and time go today (our data)

Source: `GET /api/v1/executions/{id}` on 28 completed `sdlc-implement-v3` and
`sdlc-implement-v4-precheck` runs, from the 100 most recent executions, read
2026-10-17. Costs are the platform's API-equivalent USD. The VPS bills a
subscription, so read these as quota share, not invoice.

| Phase | Model (resolved) | n | Sum | Share | Median cost | Median min |
|---|---|---|---|---|---|---|
| implement | claude-opus-5-5 | 25 | $68.4 | 28.7% | $1.92 | 43.0 |
| verify | gpt-6.1-sol | 26 | $54.2 | 22.7% | $1.73 | 37.0 |
| fix | claude-opus-5-5 | 22 | $36.8 | 15.5% | $1.66 | 35.5 |
| reverify | gpt-6.1-sol | 22 | $20.1 | 8.4% | $0.86 | 8.6 |
| premise | claude-opus-5-5 | 23 | $17.4 | 7.3% | $0.74 | 2.3 |
| finalize_pr | claude-opus-5-5 | 28 | $16.8 | 7.0% | $0.65 | 1.7 |
| fix_2 | claude-opus-5-5 | 16 | $15.9 | 6.7% | $0.98 | 18.0 |
| reverify_2 | gpt-6.1-sol | 16 | $8.7 | 3.6% | $0.41 | 6.1 |

Total: $238 over 28 runs (about $8.50 per completed run).

### Current per-phase assignments

| Workflow | Phase(s) | Model |
|---|---|---|
| sdlc-implement-v2 / v3 / v4-precheck | premise, implement, fix, fix_2, finalize_pr / open_pr | claude-opus-5-5 |
| same | verify, reverify, reverify_2 | gpt-6.1-sol (codex), Opus fallback |
| sdlc-pr-review-v1, -slp-v1 | investigate / verify / report | opus / gpt-6.1-sol / **sonnet** |
| sdlc-quickfix-v1 | quickfix | **sonnet** |
| sdlc-retrospective-v1 | gather, file | **sonnet** |
| sdlc-decision-record-v1, research-experiment-plan-v1 | all | opus, with gpt-6.1-sol reviews |

No eval justifies any of the **sonnet** rows. Under the owner rule (Opus by
default, Sonnet only with eval proof), each one is an open question, not a
decision.

## 2. Public evidence by task

Every source below was accessed on 2026-10-17. "Vendor claim" means the number
was published by the model's maker and has not been reproduced independently.

### Implementing

- Artificial Analysis independent Coding Agent Index: Opus 5.5 and Sonnet 5.5
  (both in Claude Code) rank first and second, ahead of GPT-6.1 Sol in Codex
  [5]. On its Intelligence Index, Opus 5.5 scores 58, Sonnet 5.5 56 and
  GPT-6.1 Sol 52 [5].
- Vendor claim: on Terminal-Bench 4.0, Sonnet 5.5 scores 70.6% and Opus 5.5
  66.4%. Opus 5.5 leads on CursorBench (57.8 vs 55.5) and FrontierCode (54.4
  vs 46.2) [6][7].
- Vendor claim: Opus 5.5 beats Fable 5.1 on every row of Anthropic's table [6].
  This supports the owner's rule that Fable runs only when an eval shows a need.
- SWE-bench Verified is retired as contaminated [23]. Scale's SWE-bench Pro has
  no Claude 5.x or GPT-6 entries yet [24]. Do not use the aggregator figure
  "Opus 5.5 89.9%" on SWE-bench Pro; it has no primary source [25].

### Verifying and code review

- No public benchmark measures base models as reviewers. ReviewBench, which is
  published by a vendor with its own product entered, compares whole review
  products. Every entry has precision around 86% and recall of 18 to 23% [9].
  A Sonnet 5.5-based reviewer scored F1 35.9%. Codex on GPT-5.6 Sol (not 6.1)
  scored F1 30.4%.
- Reviewers score F1 0.85 on injected bugs and 0.07 on real PRs [10]. That is
  why our suites mine real escaped defects; keep it that way.
- Vendor claim (a customer quote): Opus 5.5 "caught 72% of known bugs" [6].
- The binding constraint is **recall** (missed bugs), which matches our quality
  metric, escaped defects per merged PR.

### Cross-family verification (supports the owner rule)

- When two models are both wrong, they agree on the wrong answer more often if
  they share a vendor. Frontier models converge even across vendors [11][12].
- Self-preference: judges favor outputs they recognize as their own [18].
  Contested: about half of earlier self-preference results lose significance
  once you control for the judge's competence [20].
- Self-correction without external feedback is weak [21]. On code, feedback
  from a stronger model beats a model's own feedback [14].
- Implication: keep cross-family verification, and keep tests as external
  evidence. Whether a cheap GPT tier keeps the cross-family benefit is
  unmeasured. E1 measures it.

### Planning, mechanical edits and triage

- Planning: Anthropic says to start with Opus 5.5 and move to Fable 5.1 only
  when Opus at higher effort falls short [1]. No planning benchmark exists.
- Mechanical edits and triage: Haiku 5.5 is positioned for classification and
  routing [1]. GPT-6 Luna is positioned for high volume [3]. Both are
  positioning, not measurement.
- Cheaper model after an expensive one: architect/editor splits gained 3 to 10
  points with 2024 models [4]. RouteLLM routing cut cost more than 2x at equal
  quality [22]. Claude Code's `opusplan` has Opus plan and Sonnet implement
  [8]. There is no 2026 controlled study of a cheaper model doing a fix phase.

## 3. Prices (USD per Mtok)

These match `packages/syn-shared/src/syn_shared/pricing/__init__.py` where the
model is registered.

| Model | Input | Cache read | Output | In platform registry |
|---|---|---|---|---|
| claude-fable-5-1 | 10 | 0.25 | 50 | not checked |
| claude-opus-5-5 | 4 | 0.20 | 20 | yes |
| claude-sonnet-5-5 | 2 | 0.10 | 10 | yes |
| claude-haiku-5-5 | 0.10 | 0.01 | 0.50 | **no** (`haiku` alias maps to claude-haiku-4-5) |
| gpt-6.1-sol | 2 | 0.10 | 10 | yes |
| gpt-6-luna | 0.10 | 0.01 | 0.50 | yes |
| gpt-5.6-terra | 2 | 0.20 | 12 | yes |
| gpt-5.6-luna | 0.20 | 0.02 | 1.20 | yes |

## 4. Phase x model recommendation (prior, before our experiments)

| Phase | Recommendation now | Candidate to test | Confidence | Evidence |
|---|---|---|---|---|
| premise, plan | Opus 5.5 | none yet | Low | vendor guidance only |
| implement | Opus 5.5 | Sonnet 5.5 (E2) | Medium | [5][6][7], vendor-heavy |
| verify, reverify | gpt-6.1-sol (cross-family) | none (gpt-6-luna rejected, E1) | Medium | indirect [11][14][18] |
| fix, fix_2 | Opus 5.5 | Sonnet 5.5 (E3, after E2) | Low | [4][7][8][22] |
| finalize_pr, report | Opus 5.5 | Sonnet 5.5 (later; 14% of spend) | Low | positioning only |
| triage / screener | see PR #2015 bench | Haiku 5.5 / gpt-6-luna | Low | positioning only |

E2 update (2026-10-18): on implementer-seed-v1 v3, Sonnet 5.5 passed 5/10
and Opus 5.5 6/10. Sonnet cost about 1/4 as much ($0.46 vs $1.98 mean per
implement run) and was about 7x faster (4.1 vs 27.3 min). This passes the
preregistered "proceed" bar exactly on the boundary: no evidence of a large
drop, not equivalence. The implement row stays Opus 5.5. Sonnet becomes a
candidate for the fix phases (E3), whose production guards decide.
Details: `docs/experiments/2026-10-17-implementer-sonnet-vs-opus.md`.

E1 update (2026-10-18): gpt-6-luna is REJECTED as the verifier. On
verifier-seed-v1 train (26 defect cases), Sol caught 18 and Luna 12 (b = 9,
c = 3), and Luna false-blocked a clean control Sol certified. On verdict
alone Luna certified 5 known defects; Sol blocked all 26. Luna is ~19x
cheaper per run ($0.0125 vs $0.233), which does not pay for the escapes.
The verify row stays gpt-6.1-sol. Sol also caught a real bug in a "clean"
control (#2030). Details: `docs/experiments/2026-10-17-verifier-gpt-6-luna-vs-sol.md`.

## 5. Defects found while doing this research

1. (#2020) The `haiku` alias resolves to `claude-haiku-4-5-20251001`
   (`packages/syn-shared/src/syn_shared/agents.py:354`), a pre-5 model.
   claude-haiku-5-5 is not registered.
2. (#2021) The eval LLM judge is pinned to `claude-sonnet-4-6`
   (`evals/verifier-seed-v1/README.md`, `scripts/eval_suite.py`), a pre-5
   model. Until it is moved, use the keyword judge only.
3. Pinned CLI 2.1.281 may resolve `sonnet` to Sonnet 5, not 5.5
   (`agents.py:399-403`). Any Sonnet arm must check `phases[].model`.
4. (finding, no issue) The `launches.jsonl` ledgers hold only v1/v2 runs. The
   v3 to v8 history in `evals/verifier-seed-v1/suite.yaml` refers to runs that
   are not recorded anywhere, so no v3-v8 score can be reproduced.
5. (finding, no issue) gpt-6.1-sol was launched on verifier-seed-v1 v2 (6 runs)
   and never scored. `eval-verify-pinned-sonnet-v1`, the three cheaper-codex
   verifier workflows (`gpt-6-luna`, `gpt-5.6-luna`, `gpt-5.6-terra`) and
   `eval-implement-pinned-v1` have never run. Our cross-family rule and our
   choice of verifier model rest on n=4 (Opus v1) plus production block rates.

## 6. Unknown

- How well Opus 5.5 and gpt-6.1-sol do as reviewers on our cases, by recall and
  by false blocks. No public data exists, and our own data is n=4.
- Whether a cheap GPT tier keeps the cross-family benefit.
- Whether Sonnet 5.5 holds quality on fix phases, where context from the
  verifier's findings matters more than raw capability.
- Independent SWE-bench Pro and METR numbers for Claude 5.x and GPT-6.

## Citations (all accessed 2026-10-17)

1. https://platform.claude.com/docs/en/about-claude/models/overview
2. https://platform.claude.com/docs/en/about-claude/pricing
3. https://developers.openai.com/api/docs/pricing
4. https://aider.chat/2024/09/26/architect.html
5. https://artificialanalysis.ai/agents/coding-agents ; https://www.deeplearning.ai/the-batch/sol-nearly-eclipses-astra
6. https://www.anthropic.com/claude-opus-5-5 (vendor)
7. https://www.anthropic.com/claude-sonnet-5-5 (vendor)
8. https://code.claude.com/docs/en/model-config (vendor)
9. https://benchlm.ai/benchmarks/reviewbench
10. https://arxiv.org/html/2606.15689v1
11. https://arxiv.org/abs/2506.07962
12. https://arxiv.org/abs/2502.04313
14. https://arxiv.org/abs/2306.09896
18. https://arxiv.org/abs/2404.13076
20. https://arxiv.org/abs/2601.22548
21. https://arxiv.org/abs/2310.01798
22. https://arxiv.org/abs/2406.18665
23. https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
24. https://labs.scale.com/leaderboard/swe_bench_pro
25. https://benchlm.ai/benchmarks/swe-bench-pro

Source caveats: openai.com returned 403, so OpenAI figures come from its docs
pages and secondary coverage. Numbering follows the research notes; the gaps
are sources not cited in this doc.
