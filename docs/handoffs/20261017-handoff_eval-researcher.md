# Handoff: eval researcher (model selection for SDLC workflows)

Written 2026-10-17 by the Syn137 Orchestrator (session `syntropic137-62`) at the owner's request.
You are a long-lived research session started in herdr. Check in with `syntropic137-62` first.

## Goal

Find out which model to use for which workflow phase so Syntropic137's SDLC
workflows **keep the quality bar** while costing less and finishing faster.
Quality first, then cost and time (`.claude/skills/orchestrating/SKILL.md`).

Two halves, both required:

1. **Online research:** the current best understanding (as of October 2026) of
   which models do best at which software-engineering tasks: implementing,
   verifying/reviewing, planning, mechanical edits, triage. Cite every claim
   with URL and accessed date; prefer primary sources (vendor model cards,
   benchmark leaderboards with methodology, peer-reviewed or reproducible
   evals). Mark vendor marketing as such.
2. **Learning experiments on our own service:** turn the research into
   hypotheses and test them on the platform with our eval suites, one variable
   at a time.

## Deliverables

- `docs/research/2026-10-17-model-selection-for-sdlc-phases.md`: findings,
  citations, a phase x model recommendation table with confidence, and what is
  still unknown.
- `docs/experiments/<date>-<slug>.md` per experiment, preregistered BEFORE
  running (hypothesis, arms, metric, sample size, stop rule), results filled in
  after, following `.claude/skills/workflow-experimentation/SKILL.md`.
- A draft PR from branch `research/eval-model-selection` (this worktree). Do
  not merge; the orchestrator reviews and lands it.

## What exists (read these first)

- Skills: `.claude/skills/workflow-experimentation/SKILL.md`,
  `.claude/skills/learning-loop/SKILL.md`, `.claude/skills/orchestrating/SKILL.md`.
- Eval suites: `evals/verifier-seed-v1/`, `evals/implementer-seed-v1/`;
  runner `scripts/eval_suite.py` (`score`, `launch`, `--api-url`). Escaped-bug
  seed cases are in `.claude/skills/learning-loop/SKILL.md`.
- Prior experiment: `workflows/sdlc/implement-v4-precheck/EXPERIMENT.md`
  (v4-precheck A/B, provisional ADOPT; treatment 4 fix phases vs 6, median time
  to ready ~6.7h vs ~12h).
- Feedback screener bench (System-1 classifier choice): PR #2015, plan PR #2010
  section 2.10.
- Platform: workflows and per-phase models in `workflows/`; execution records
  with per-phase model and cost at `GET /api/v1/executions/{id}`.

## Owner decisions already made (do not relitigate; test within them)

- Default is **Opus 5.5** everywhere. A cheaper model (Sonnet 5.5) is adopted
  for a phase only with eval proof that quality holds. Fable only if an eval
  shows a need.
- **Cross-family verification:** Opus implements, GPT-6.1 verifies (and vice
  versa). Sonnet certified 2 real bugs as clean once; it is not a verifier
  until an eval says otherwise. Exploring cheaper GPT verifiers via evals is
  welcome.
- Never run pre-5 Claude models (no Sonnet 4.x). Resolve aliases to explicit
  model ids in anything you report.
- Escaped defects per merged PR is the quality metric that gates every change.

## How to reach the platform

- API: `http://100.114.86.77:8137/api/v1`, Basic auth user `admin`, password
  from Keychain `syn137-api-password-vps`. Use the pinned helpers in
  `/Users/neural/Code/Syntropic137/orchestrator-bin` (`syn137-api`, `syn137`),
  never `curl $(...)` (security hooks block it).
- Usage: `curl -s http://127.0.0.1:8123/usage | jq '.providers'`. The VPS bills
  `claude@bryce` right now.

## Hard limits

- **Platform runs:** at most **2 of your own runs in flight**, each tagged
  `--tag eval-research`. Message `syntropic137-62` before each dispatch with
  the workflow, arm and expected cost; the orchestrator keeps the VPS at about
  4 runs total and may say "wait".
- **Budget:** stop dispatching and message the orchestrator if Claude weekly
  for the VPS account is under 20% or a run fails on a usage limit.
- **No** local docker, ssh, or repo clones in subagents (the owner gets unsafe
  permission prompts). Read the VPS through the API only.
- **No** merges, releases, pit stops, `.github/` edits, or VPS changes.
- **Never** print secrets or `.env` contents.
- Use `uv run` for Python. No em dashes in files.
- Commit to this worktree's branch only; never switch branches in
  `/Users/neural/Code/Syntropic137/syntropic137` (the main checkout).

## Suggested first steps

1. Message `syntropic137-62`: your session name and this handoff path.
2. Read the skills and EXPERIMENT.md above; list our current per-phase model
   assignments from `workflows/` (table: workflow, phase, model).
3. Do the online research and write the first draft of the research doc.
4. Propose 2-3 preregistered experiments (for example: Sonnet 5.5 vs Opus 5.5
   on the fix phase against `implementer-seed-v1`; a cheaper GPT verifier vs
   GPT-6.1 on `verifier-seed-v1`). Send them to the orchestrator before running.
5. Report progress to the orchestrator every few hours or at each result.
