# Dogfood run log — 2026-08-29 onward

A working log of the autonomous dogfooding push: what was done, the hypothesis
behind it, and what the evidence said. Appended per 30-minute tick.

Kept separate from the decision brief: the brief says where things STAND, this
says how they got there and what was learned on the way. The retrospective at
the bottom is the part worth reading later.

---

## Standing hypotheses under test

| # | Hypothesis | Status |
|---|---|---|
| H1 | Separate, focused phases beat fewer combined phases | **supported, n=1** — 62% → 75% citation accuracy for +5.6% cost |
| H2 | SLP skills in research/planning improve plan quality | **untested** — the skills run died on an unregistered ref |
| H3 | Cross-model review catches what the author cannot | **supported** — codex found a live path traversal in #995 |
| H4 | A workflow can do real work on this repo unattended | **supported** — PR #992 opened for $1.09, but shipped red CI |
| H5 | Mechanical scoring beats opinion for comparing runs | **supported** — the citation scorer produced the H1 result |

---

## Tick log

### Tick 1 — drive #988 and #964

**Did:** reviewed the #988 subagent's PR #995 rather than accepting its green
suite. Independently re-ran one of the three mutations it reported as initially
surviving.

**Why:** an agent reporting its own mutation results is marking its own homework.

**Found:** the report held — but I nearly filed two false negatives against it.
My first check said "0 tests collected" (my grep was broken; it was 15) and my
mutation appeared to survive (I ran the wrong scope — this repo colocates tests
in `src/` AND `tests/`). **Both errors were mine, in the act of checking someone
else's work.**

### Tick 2 — codex review of #995

**Hypothesis:** the risky surface is path traversal between phases, because the
injected path is built from a file the agent itself wrote.

**Result:** hypothesis half right, and the half I got wrong is the interesting
part. An agent writing `artifacts/output/../../etc/foo` writes to
`/workspace/etc/foo`, which the collection glob never picks up — that vector is
dead. The REACHABLE input was `phase_id`, which was `min_length=1` and nothing
else, so `../../../tmp/owned` validated. Injection joins that to the HOST-side
workspace directory.

**Pre-existing**, not introduced by #995 — `main` already built
`f"artifacts/input/{phase_id}.md"` from the same unvalidated id.

**Fixed** with an allowlist grammar plus independent containment at the sink,
because the grammar protects new workflows while `source_path` still arrives
from the projection on the recovery path. Not filed publicly: the repo is public
and the hole was live.

**Incidental find:** writing the tests showed an ABSOLUTE `source_path` does not
escape — joining collapses the slashes and `/etc/passwd` lands inside the phase
directory. Contained, but it silently becomes a file nobody described, so it is
refused explicitly.

### Tick 3 — #964 merged

**Did:** verified the load-bearing claim empirically instead of from `--help`.

```
$ claude -p "Run 'echo SHOULD_NOT_RUN'... else say NO_BASH" --tools "Read"
NO_BASH — I don't have a Bash tool available in this session
```

**Why it mattered:** the entire PR rests on `--tools` restricting availability.
`--help` text describing a flag is not evidence that it does what you think.

**Also found:** `--tools` is VARIADIC and greedy — placed before the prompt it
eats the prompt. The merged argv is safe only because the prompt precedes it,
and nothing says so. Flagged for an argv-ORDER assertion.

**Correction carried:** `max_tokens` is not un-forwarded, it is UNFORWARDABLE.
No token flag exists in either CLI.

### Tick 4 — #992 closed, and the best lesson so far

**Did:** closed the PR Syntropic wrote for itself, and closed my own issue #989
as invalid.

**Why:** all six "hardcoded literals" I told it to fix were inside DOCSTRINGS,
including a `>>>` doctest. The agent did exactly what the issue said. The issue
was wrong.

**The lesson:** a confident, file-and-line-accurate instruction that nobody
checked against what those lines actually WERE. CI caught it only as "unused
import" — the shallowest possible symptom of "this change should not exist".

This is the argument for H1 and H3 in one incident: a separate research phase
and a cross-model reviewer both exist to catch a wrong premise before it becomes
a PR.

### Tick 5 — experiment 2, and a P0

**Hypothesis (H1):** four isolated phases beat three combined.

**Method:** same task (#990), same repo, same models, same day. Only variable:
phase count. Scored mechanically with `score_plan_citations.py`.

| | v1 (3 phases) | v2 (4 phases) |
|---|---|---|
| cost | $3.3246 | $3.5111 (+5.6%) |
| citations resolving | 13/21 (62%) | 9/12 (75%) |
| total citations | 21 | 12 |

**+5.6% cost bought +13 points of accuracy.** The subtler signal: v2 made FEWER
claims and got more of them right — which is what splitting "find out what is
true" from "decide what to do" should produce.

**The P0 (#998):** the skills variant returned `200 {"status":"started"}` and
the execution never existed. Isolated by stripping the nine skill refs; the
control ran to completion.

**Root cause, from the API log:** `SkillNotRegistered` — skills must be
registered before a workflow may reference them. **That refusal is correct and
its message is excellent** (names the skill, source, version, and two remedies).
The defect is that all of it went to a log file while the API said 200.

`_resolve_phase_skills` runs after the 200 and before the aggregate is first
persisted, so a failure there is unattributable by construction. Plugin
resolution and repo hydration share that window.

### Tick 6 — release PR #999 opened

**Did:** bumped to v0.27.0, pushed to main, opened the release PR.

**Why 0.27.0 and not a patch:** the delegate import ledger, phase output
directories, real tool restriction, and a path-traversal fix are behaviour
changes.

**Notable friction:** the version leaks into four generated artifacts
(`uv.lock` and three plugin schemas), each needing its own regeneration pass.
Three separate preflight failures before the tree was clean.

**Release notes name the breakage** rather than burying it: `max_tokens` is now
a validation error, phase ids are constrained, unknown YAML keys are rejected.
#998 and #997 are listed as Known Issues — someone should see those before
upgrading.

---

## Retrospective

### What worked

**Mechanical scoring changed the conversation.** "Which plan is better" is
unanswerable; "13/21 citations resolve" is a number that survives to next week
and can be compared across models and harnesses. Building the scorer took
minutes and produced the only real evidence for H1.

**Cross-model review earned its cost twice.** Codex found a live path traversal
and the alias-divergence bug, neither of which the author or I saw.

**Running the thing found what reading it could not.** Every P0 today came from
executing a workflow, not from reading code. #998 in particular is invisible
from the source — you only see it when a 200 leads nowhere.

### What went wrong, and the pattern

I was **wrong four times today, always in the same direction**: I asserted from
reading, and evidence contradicted me.

1. #988 reported as "verified" when only read, not executed.
2. Claimed the dogfood run "couldn't" run preflight; it ran it twice and ignored
   the result.
3. Predicted the traversal vector; the real one was elsewhere.
4. Filed #989 listing six "call sites" that were docstrings — and an agent built
   a PR on it.

The fourth is the costly one, because a wrong premise propagated into someone
else's work.

**Also: three of my own tests could not fail** until mutation-tested. Two used
xfail, which is satisfied by ANY failure including an AttributeError that never
reaches the assertion.

### What to do differently

- **Execute before asserting.** A claim is a hypothesis until something runs.
- **Mutation-test every test.** Revert the fix; if nothing fails, the test is
  decoration.
- **Verify the measurement before doubting the measured.** Twice I nearly filed
  false negatives against an agent because my own grep or scope was wrong.
- **Check the premise of an issue before delegating it.** #992 cost a full
  workflow run and a PR because nobody looked at what the cited lines were.

### Open threads

- **H2 untested.** Register the SLP skills, then re-run v2 with them.
- **SSH to the Mini is intermittent** (1Password agent), which gates log access.
- **The Mini runs v0.26.0**, so no self-host run yet exercises #988 or #964.
