# Eval best practices for coding-agent workflows

Date: 2026-10-07. Status: research synthesis, input to #967 (see
[docs/plans/20260929_evals-and-execution-tags.md](../plans/20260929_evals-and-execution-tags.md)
and `evals/verifier-seed-v1/`). Docs only, no code changes.

Question: how do mature eval frameworks and the coding-agent benchmark
literature model, build, judge and compare evals, and what should
Syntropic137 adopt so that "same quality, lower cost/time" is a claim we can
defend?

## 1. Data model: what the frameworks agree on

| Concept | Inspect AI | Anthropic agent evals | OpenAI Evals API | Braintrust / Langfuse | Terminal-Bench / Harbor |
|---|---|---|---|---|---|
| Unit of work | Sample (input, target, metadata, files, setup) | Task | data item | dataset item | task (instruction, image, tests, reference solution, time limit) |
| Collection | Dataset inside a Task | Suite | data_source_config | Dataset (versioned) | dataset |
| Thing under test | Solver / agent | Agent harness | model + prompt in a run | task function | agent + model |
| Judge | Scorer (+ metrics) | Grader (code, model, human) | testing_criteria (graders) | scorers | tests on final container state |
| One attempt | epoch of a sample | Trial (+ transcript, outcome) | run output | span / trace | trial |
| Comparison | eval log per run, `inspect score` re-scoring | capability vs regression suite | run | Experiment (immutable), dataset run | leaderboard |

Sources: [Inspect](https://inspect.aisi.org.uk/),
[Inspect metrics and epoch reducers](https://inspect.aisi.org.uk/metrics.html),
[Anthropic, Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents),
[OpenAI evals guide](https://developers.openai.com/api/docs/guides/evals),
[Braintrust evals](https://www.braintrust.dev/docs/guides/evals),
[Langfuse datasets](https://langfuse.com/docs/evaluation/dataset-runs/datasets),
[Terminal-Bench paper](https://arxiv.org/abs/2601.11868).

Consistent patterns:

- **Task and judge are separable.** Inspect re-scores an existing log with a
  new scorer without re-running the agent; Braintrust and Langfuse attach
  scores to traces after the fact. Judgments are a separate, append-only
  record keyed by (trial, judge, judge version).
- **Identity of a task = instruction + starting state + success criteria.**
  Terminal-Bench pins a Docker image and ships tests plus a reference
  solution; SWE-bench pins repo@base_commit, an environment, and
  FAIL_TO_PASS / PASS_TO_PASS test lists
  ([SWE-bench](https://arxiv.org/abs/2310.06770)). The reference solution
  proves the task is solvable and the tests accept a correct answer.
- **The variant is not part of the task's identity.** Model, harness, prompt,
  tools and effort are run configuration. Braintrust makes each
  configuration an immutable experiment; Langfuse versions datasets by
  timestamp so a run is reproducible against the dataset as it was.
- **Trial is first class.** Anthropic: "a trial is one attempt at a task";
  Inspect has `epochs` with reducers `mean`, `pass_at_k`, `pass_k`
  (pass^k), `at_least_k`.
- **Versioning is explicit and coarse.** Inspect records task version and
  package version in the log; any change to a sample, its environment or its
  scorer is a new version, and old scores stay attached to old versions.

## 2. Building datasets from our own history

SWE-bench is the template: start at the parent of a real merged fix, hide the
fix's tests, grade FAIL_TO_PASS (tests that must flip) plus PASS_TO_PASS
(tests that must not break). Its history is mostly a list of ways this goes
wrong:

- **Weak and narrow tests.** SWE-bench+ found 31% of "passing" patches passed
  only because tests were weak and 33% had the solution leaked in the issue
  text ([Aleithan et al.](https://arxiv.org/abs/2410.06992)). SWE-bench
  Verified had humans screen 500 tasks for under-specification and bad tests
  ([OpenAI](https://openai.com/index/introducing-swe-bench-verified/)); in
  Feb 2026 OpenAI stopped using it after auditing hard tasks and finding most
  flawed (narrow tests enforcing one implementation, wide tests checking
  unrequested behaviour) plus signs of contamination
  ([OpenAI](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)).
  The ABC checklist calls these task validity and outcome validity and found
  flaws in 7 of 10 agentic benchmarks
  ([Zhu et al.](https://arxiv.org/abs/2507.02825)).
- **Contamination.** Our repo is public, so frontier models may have trained
  on it. SWE-rebench keeps a rolling window of tasks created after each
  model's release date and tags results with that
  ([SWE-rebench](https://arxiv.org/abs/2505.20411)). Record each case's fix
  date so scores can be split pre/post model cutoff.
- **Leakage from the environment, the agent-specific version.** The agent
  can `git log`, fetch, or browse GitHub and find the fix. Pin the commit
  with no later history reachable (shallow clone or rewritten refs), and
  block or allow-list network egress to the repo and its PRs. Inspect,
  Terminal-Bench and SWE-bench all run in containers with pinned images for
  this reason.
- **Determinism.** Pin repo@sha, workspace image digest, dependency lockfile,
  and the test command. Run the hidden tests several times at both the
  parent (must fail) and the fix (must pass) before admitting a case; drop
  anything flaky. Multi-SWE-bench needed 68 annotators to cut 2,456
  candidates to 1,632 valid ones
  ([Multi-SWE-bench](https://arxiv.org/abs/2504.02605)), so expect a
  low admission rate.
- **Stronger graders than unit tests.** SWE-Lancer replaced unit tests with
  end-to-end tests triple-verified by engineers because unit tests let
  incorrect patches through ([SWE-Lancer](https://arxiv.org/abs/2502.12115)).
- **Size.** Anthropic: "20-50 simple tasks drawn from real failures is a
  great start." That is enough to find large effects and to debug graders,
  not to certify small ones (section 4).
- **Holdout.** Once you optimise prompts, skills and workflows against a
  suite, it stops measuring generalisation. Kapoor et al. list holdout sets
  as a core requirement of agent benchmarks and show many lack one
  ([AI Agents That Matter](https://arxiv.org/abs/2407.01502)). The
  Leaderboard Illusion shows how selective private testing inflates public
  scores ([Singh et al.](https://arxiv.org/abs/2504.20879)).
- **Capability vs regression.** Anthropic separates capability suites (low
  pass rate, hill-climb) from regression suites (near 100%, must stay there),
  and graduates solved capability tasks into regression.

## 3. Judges

**Prefer deterministic.** Anthropic: code-based graders are "fast, cheap,
objective, reproducible" but brittle to valid variation; grade "what the
agent produced, not the path it took." For coding: hidden tests, build/lint
gates, structured field matching (verdict = blocked, file named).

**LLM-as-judge, known biases:**

- Position, verbosity and self-enhancement bias; GPT-4 judges reached ~80%
  agreement with humans, about human-human level
  ([Zheng et al., MT-Bench](https://arxiv.org/abs/2306.05685)).
- Position bias is systematic and varies by judge and task
  ([Shi et al., Judging the Judges](https://arxiv.org/abs/2406.07791));
  a 2026 follow-up finds style bias far larger than position bias
  ([2604.23178](https://arxiv.org/abs/2604.23178)).
- Self-preference: judges recognise and favour their own outputs, and the
  effect scales with self-recognition
  ([Panickssery et al.](https://arxiv.org/abs/2404.13076)). Relevant when an
  Opus judge grades Opus vs Codex.
- G-Eval (CoT + form-filling) improved correlation with humans but also
  showed a bias toward LLM-written text
  ([Liu et al.](https://arxiv.org/abs/2303.16634)).

**Rubric and calibration practice:**

- Binary pass/fail plus a written critique beats 1-5 scales; the critiques
  become few-shot examples ("critique shadowing")
  ([Husain](https://hamel.dev/blog/posts/llm-judge/)).
- Measure the judge against human labels as a classifier: report
  precision/recall or Cohen's kappa on a labelled set, not raw agreement
  ([Yan](https://eugeneyan.com/writing/llm-evaluators/)).
- Criteria drift: you only learn the criteria by grading outputs, so the
  rubric changes after you read transcripts
  ([Shankar et al.](https://arxiv.org/abs/2404.12272)). Hence: version the
  judge, keep old judgments, re-score.
- Multiple judges: use a judge from a different model family than the agent
  under test, swap order for pairwise judgments, and treat disagreement as a
  "needs human" signal rather than averaging it away.
- Read transcripts. Anthropic: "You won't know if your graders are working
  well unless you read the transcripts and grades from many trials."

**Judge identity** = judge kind + prompt/rubric hash + model id (exact, not
alias) + parameters + code version. Any change is a new judge version.

## 4. Statistics

- **pass@k vs pass^k.** pass@k: at least one of k trials succeeds (Codex
  paper unbiased estimator `1 - C(n-c,k)/C(n,k)`,
  [Chen et al.](https://arxiv.org/abs/2107.03374)). pass^k: all k succeed,
  estimator `C(c,k)/C(n,k)` ([tau-bench](https://arxiv.org/abs/2406.12045)).
  A 75% per-trial agent has pass^3 of ~42%. A workflow that ships code
  unattended needs pass^k; a "try a few and pick one" flow can use pass@k.
- **Agents are noisy.** tau-bench: the best agent (gpt-4o) scored about 60%
  pass^1 in retail but under 25% pass^8. SWE-rebench runs each model 5 times. HAL ran 21,730 rollouts and
  found higher reasoning effort reduced accuracy in most runs
  ([HAL](https://arxiv.org/abs/2510.11977)). One run per variant is an
  anecdote.
- **Error bars, clustered and paired.** Report standard errors; cluster by
  task when there are multiple trials per task; compare variants paired on
  the same tasks, which removes task-difficulty variance
  ([Anthropic, statistical approach](https://www.anthropic.com/research/statistical-approach-to-model-evals),
  [Miller](https://arxiv.org/abs/2411.00640)). For binary paired outcomes,
  McNemar on discordant tasks is the simple version; a task-clustered paired
  bootstrap handles k trials and cost together.
- **How many runs.** Unpaired, 30 tasks at p=0.7 give SE ~8pp, a 95% CI of
  +-16pp. Paired with k=3 trials, the per-task difference SD is typically
  ~0.3 (an assumption; measure it), so SE ~ 0.3/sqrt(n): 30 tasks -> 5.5pp,
  56 tasks -> 4pp. To show non-inferiority within a 10pp margin with ~80%
  power you need SE ~4pp, i.e. ~50-60 tasks x 3 trials per variant. At 20-30
  tasks you can only rule out regressions of ~15pp. State the margin you
  can actually detect.
- **"Same quality" is a non-inferiority claim, not a failed significance
  test.** "No significant difference" on 6 cases says nothing. Pre-register
  a margin and require the CI's worst end to sit inside it.
- **Cost-quality Pareto.** Kapoor et al.: simple baselines Pareto-dominate
  complex agents at up to 50x lower cost; evaluation must control for cost.
  Aider's polyglot leaderboard reports percent correct beside total cost
  ([aider](https://aider.chat/docs/leaderboards/)). Plot pass rate vs cost
  per task with CIs on both axes; only Pareto-frontier variants are
  candidates.

## 5. Eval vs benchmark; leaderboards

Practitioner usage: an **eval** is your own measurement, tied to your
product's tasks, used to make decisions (regression, capability, cost).
A **benchmark** is a fixed, shared task set used to compare systems, usually
public, usually with a leaderboard
([HELM](https://arxiv.org/abs/2211.09110) for multi-metric, standardized
scenarios). Your eval cases can form a private benchmark when you hold the
cases and judges fixed and vary the agent.

Leaderboard design lessons:

- Say what varies: Terminal-Bench lists agent+model pairs and ships a neutral
  harness (Terminus) to isolate model from scaffold; SWE-bench separates
  constrained (bash-only) from open scaffolds.
- Report CIs, trial count, cost and date, not a single number
  (HAL, ABC "benchmark reporting").
- Tag rows with contamination window (SWE-rebench) and suite version.
- Keep a holdout the optimisers never see; publish only frozen versions.
- METR's time-horizon metric
  ([Kwa et al.](https://arxiv.org/abs/2503.14499)) weights tasks by
  human-time-to-complete; useful later for mixing easy and hard cases.

## 6. Token and cost efficiency for agents

Measure per trial, store in Lane 2, aggregate per variant:

- tokens by kind: input, output, cache write, cache read (priced very
  differently; Anthropic cache reads are ~0.1x input), and **dollars**
  computed from them with the exact model id
- turns / tool calls, and peak context size
- wall clock, plus time to first useful action
- **cost per solved task** = total cost / tasks solved (the honest unit;
  cheap failures are not savings)
- judge cost separately from agent cost

On our measured problem: 8.8M tokens at 99% cache reads over ~200 tool calls
is ~44K tokens re-read per turn. Cumulative cache reads scale with turns x
context size, so the levers are fewer turns and smaller context (focused
scope, subagents with fresh context), not cheaper tokens. A focused verifier
at ~1M is a natural first variant, but it is only a win if its catch rate on
the verifier suite is non-inferior and its false-block rate on clean
controls is not worse (section 7).

## 7. Recommendation for Syntropic137

### Entities and fields

Keep the existing `Eval` aggregate as the case; separate case identity from
variant (today `suite.yaml` bumps the suite version when a workflow's model or
prompt changes, which conflates them).

| Entity | Key fields |
|---|---|
| **EvalCase** (existing `Eval`) | id, version, kind (`verifier` / `implementer` / `workflow`), task prompt, Baseline (repo@sha per repo), workspace image digest, network policy, hidden test refs (FAIL_TO_PASS, PASS_TO_PASS) or expected findings, reference solution sha, judge ids, split (`dev` / `holdout`), polarity (`defect` / `clean-control`), provenance (escaped-bug issue, fix PR, fix date), contamination date |
| **Suite** | id, version, case ids + versions, judge versions. Version bumps only when cases or judges change |
| **Variant** | content hash over workflow def, per-phase harness, exact model, effort, prompt hashes, skills, tools, image digests. Never an alias |
| **Trial** (= execution) | eval_id, variant hash, trial index, `checked_out_commits`, outcome artifacts, Lane-2 metrics (tokens by kind, cost, tool calls, turns, peak context, wall clock) |
| **Judgment** | trial id, judge id, judge version, verdict (pass/fail), score, critique, judge cost. Append-only; re-scoring adds judgments, never edits |
| **Comparison** | suite version, variant A, variant B, k, split, margin, results with CIs, decision, date |

All new terms go into the owning context's ubiquitous-language file.

### Judge strategy

1. Deterministic first: hidden tests (implementer), structured verdict +
   file + finding match (verifier), build/QA gate (workflow).
2. LLM judge only for what code cannot check (is the named defect the real
   one; is the PR reviewable). Binary + critique, rubric hashed and
   versioned, from a model family different from the agent under test.
3. Calibrate each LLM judge on 30+ human-labelled trials; report kappa;
   re-check whenever the judge version changes.
4. Two judges on disagreement-prone criteria; disagreement routes to human
   review and becomes a calibration label.

### Dataset plan (first 20-50 cases)

- **Verifier, 15-20 cases:** the 6 escaped bugs, plus every escaped bug from
  retros going forward. Add an equal number of **clean controls**
  (merged, certified commits with no known defect) so a verifier that
  always blocks cannot score 100%. Report catch rate and false-block rate.
- **Implementer, 15-25 cases:** mine merged `fix:` PRs whose diff touches
  both source and tests. Start at the fix's parent; hidden tests = the fix's
  test diff. Admit only if hidden tests fail at parent and pass at the fix
  in 3 of 3 runs; PASS_TO_PASS = the touched packages' existing tests.
  Task statement from the issue, scrubbed of the solution. Human-screen
  each case for narrow/wide tests (SWE-bench Verified's lesson).
- **Whole-workflow, 5 cases:** issue -> PR on pinned sha, judged by hidden
  tests + QA gate + LLM review judge.
- Hide future history and block egress to the repo's GitHub PRs.
- Split 60/40 dev/holdout at creation, stratified by kind; holdout is
  touched only for adoption decisions. Record fix dates; prefer post-cutoff
  cases; add fresh cases monthly.

### Rule for adopting a cheaper variant

Adopt B over incumbent A when all hold:

1. Paired on the same suite version, k >= 3 trials per case per variant.
2. Non-inferiority on dev: the 95% task-clustered paired bootstrap upper
   bound of (pass_A - pass_B) < margin. Margin 5pp for regression suites,
   10pp for capability suites; with fewer than ~50 cases use the detectable
   margin instead and say so.
3. No case that A passed in all k trials fails in all k for B (protects
   pass^k on must-pass cases); verifier false-block rate not worse by more
   than the margin.
4. Cost per solved task (or wall clock, whichever is the target) lower,
   with the bootstrap CI excluding 0, or a point reduction >= 20%.
5. Repeat 2-4 once on holdout. If holdout fails, the dev win was overfit.
6. Record the Comparison; a "cheaper but slightly worse" variant inside the
   margin is adoptable; outside it, it is a different product tier, not a
   replacement.

### Five biggest pitfalls

1. **Graders that accept wrong answers or reject right ones.** Weak, narrow
   or wide tests; keyword matching that rewards naming the file without
   understanding the bug. Validate every case with a reference solution and
   a deliberately wrong solution.
2. **Answer leakage through the environment.** Future commits in `.git`,
   network access to the fix PR, issue text containing the fix, and a public
   repo in training data.
3. **Verifier suites without clean controls.** Catch rate alone rewards a
   verifier that blocks everything, which is also the most expensive one to
   live with.
4. **Noise taken for signal.** One run per variant, unpaired comparisons,
   no CIs, "no significant difference" read as "same quality."
5. **Optimising on the measuring stick.** No holdout, judges from the same
   model family as the agent, rubrics edited without versioning so old and
   new scores silently mix.

## Sources

- Anthropic, Demystifying evals for AI agents: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic, A statistical approach to model evaluations: https://www.anthropic.com/research/statistical-approach-to-model-evals ; Miller, Adding error bars to evals: https://arxiv.org/abs/2411.00640
- OpenAI evals guide: https://developers.openai.com/api/docs/guides/evals
- OpenAI, Introducing SWE-bench Verified: https://openai.com/index/introducing-swe-bench-verified/ ; Why we no longer evaluate SWE-bench Verified: https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
- SWE-bench: https://arxiv.org/abs/2310.06770 ; SWE-bench+: https://arxiv.org/abs/2410.06992 ; SWE-rebench: https://arxiv.org/abs/2505.20411 ; Multi-SWE-bench: https://arxiv.org/abs/2504.02605 ; SWE-Lancer: https://arxiv.org/abs/2502.12115
- Terminal-Bench: https://arxiv.org/abs/2601.11868 ; Aider leaderboards: https://aider.chat/docs/leaderboards/
- METR time horizons: https://arxiv.org/abs/2503.14499
- tau-bench (pass^k): https://arxiv.org/abs/2406.12045 ; Codex / pass@k estimator: https://arxiv.org/abs/2107.03374
- AI Agents That Matter: https://arxiv.org/abs/2407.01502 ; HAL: https://arxiv.org/abs/2510.11977 ; Agentic Benchmark Checklist: https://arxiv.org/abs/2507.02825 ; Leaderboard Illusion: https://arxiv.org/abs/2504.20879 ; HELM: https://arxiv.org/abs/2211.09110
- MT-Bench judge: https://arxiv.org/abs/2306.05685 ; Judging the Judges (position bias): https://arxiv.org/abs/2406.07791 ; bias mitigation: https://arxiv.org/abs/2604.23178 ; Self-preference: https://arxiv.org/abs/2404.13076 ; G-Eval: https://arxiv.org/abs/2303.16634 ; Who Validates the Validators: https://arxiv.org/abs/2404.12272
- Hamel Husain, LLM-as-a-judge: https://hamel.dev/blog/posts/llm-judge/ ; Eugene Yan, LLM-evaluators: https://eugeneyan.com/writing/llm-evaluators/
- Inspect AI: https://inspect.aisi.org.uk/ ; metrics/reducers: https://inspect.aisi.org.uk/metrics.html
- Braintrust: https://www.braintrust.dev/docs/guides/evals ; Langfuse datasets: https://langfuse.com/docs/evaluation/dataset-runs/datasets
