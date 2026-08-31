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
| H1 | Separate, focused phases beat fewer combined phases | **RESTORED, supported, n=1** — re-scored on the corrected fail-closed instrument: EXACT 62% → 75% for +5.6% cost. Identical to the original reading |
| H2 | SLP skills in research/planning improve plan quality | **RESTORED, NOT supported, n=1** — re-scored: 83% RESOLVES, 0% EXACT, 6 citations for $4.14 vs 12 for $3.51. I predicted the 0% was least likely to survive a stricter scorer; it survived unchanged |
| H3 | Cross-model review catches what the author cannot | **strongly supported, with a LIMIT found in tick 26** — it beat me repeatedly (inert #997 fix, fail-toward-good scorer, the `--tools` dispute). BUT the review INSIDE the workflow was insufficient: the revise phase overruled a correct blocker using a false premise, and an independent pass caught it |
| H4 | A workflow can do real work on this repo unattended | **supported, with a caveat** — PR #992 opened for $1.09, shipped red CI, and was ultimately closed because the ISSUE was wrong, not the work |
| H7 | A 100% mechanical citation score indicates a correct plan | **REFUTED, tick 26** — a plan scoring RESOLVES 51/51 and EXACT 51/51 was not executable. Its central claim cites a real file at real lines and the adjacent code contradicts it |
| H9 | Cross-model review's real cost is its own $0.55, not more | **REFUTED, tick 28b** — the review phase triggers the revision work. v3 revise: 6.43M cache-read, 71k out, $4.58. Same task without a real codex review: 0.38M, 13.8k, $0.23 |
| H10 | My tests find the bug I am looking for | **REFUTED across ticks 30-35** — every clever test I wrote measured the side of the boundary I was already looking at. A reviewer supplied the other side four times in six ticks |
| H24 | The review workflow's problem is its timeout number | **REFUTED, tick 57** — the number was real (300s vs the 2400s the validated planner uses) but the deeper problem is that the workflow exists ONLY as database state. `Gather Context`/`Deep Analysis` appear nowhere in the repo, so its budget could never be fixed in a PR |
| H23 | Session logs are exported as intended | **REFUTED, tick 56b** — the per-operation schema exists end to end and nothing fills it: `RecordOperationHandler` is a no-op whose body is a comment, and the one real caller writes a single synthetic totals-only operation per session (#1034). Totals are real; the history they imply is not |
| H22 | The SDLC review half is covered, because review workflows are installed | **REFUTED, tick 56** — `PR Review` and `Code Review` are both installed and have ZERO executions across all 100 runs on the Mini. Installed has been standing in for works |
| H21 | A blocker found in one run is a blocker on dispatching work generally | **REFUTED, tick 55** — #1024 rejects pushes touching `.github/workflows` only. I stopped dispatching entirely for four hours and worked locally instead. Three runs went out in parallel the moment the blocker was read precisely |
| H20 | A field wired through event, projection and API is wired end to end | **REFUTED, tick 54** — `WorkspaceCreatedEvent` is never persisted (`git grep WorkspaceCreated` outside syn-domain: 0 hits), so the field would be empty on every run. Schema tests and round-trip tests both passed; neither touched the persistence hop |
| H19 | Tests written for the bug in front of me are enough | **REFUTED, tick 53** — a fitness test written for the SHAPE of #1011/#1013/#1015 caught #969 on its first run, a field nobody was hunting, which two rounds of reading the projection had missed. Same cost, whole-class yield |
| H18 | Image identity is already captured, so #1004's image half is just plumbing | **HALF REFUTED, tick 52** — `WorkspaceCreatingEvent.container_image` is a field on an event nothing emits; `IsolationStartedEvent.image_manifest` IS populated but carries BUILD provenance, not the OCI digest, and its capture is best-effort so absence is silent |
| H17 | Widening a fix once means I have covered the bug class | **REFUTED, tick 50** — widened 2 sites -> 4 in tick 49, and codex found 4 more, including the production gateway image whose identical three lines I had removed from two sibling Dockerfiles in the same commit |
| H15 | The existing implement-from-plan workflow can turn a well-specified issue into a PR unattended | **REFUTED, tick 48c** — 3/3 phases, $4.40, zero output. The agent verified every premise and wrote the right diff; the push was rejected because the App token lacks `workflows` permission (#1024). Not a prompt-quality problem |
| H16 | A completed execution produced its deliverable | **REFUTED, tick 48c** — the same run reports `completed` with no PR and no branch. An agent that finishes without crashing produces a completed phase; task failure and harness failure are indistinguishable (#1023) |
| H13 | The v4 absence rule is citation-neutral | **REFUTED, tick 46, n=1** — v4's final plan has ZERO `file:line` citations against v3's 81 on the identical task, and its revise phase dropped 10 -> 0 where v3's rose 54 -> 81. Where v4 cites, it is 3/3 correct: density collapsed, not accuracy |
| H8 | A rule requiring the COMMAND behind an absence claim stops false-premise rejections | **STILL UNTESTED, tick 46** — the v4 run exists ($1.19 vs v3's >=$8.15, same issue) but its review returned "No blockers", so the rejection hazard never arose. Needs a run where the review DOES raise a blocker. Previously "UNBLOCKED, tick 42 — v0.27.0 deployed and verified on the Mini; codex phases now survive install. Ready to test |
| H6 | A prompt line requiring root-relative citations moves EXACT without costing RESOLVES | **strongly supported, n=3, corrected instrument** — #990: 55/55, #1004: 37/37, #1009: 51/51, all 100%. CAVEAT (tick 40): every run executed on an `edge`-channel workspace image, not `release` |
| H11 | Local QA missing CI's jobs is why CI catches more; adding them closes it | **partly supported, and incomplete — tick 44** — the six missing jobs were real and are now local. But codex showed parity is a claim about COMMANDS AND ENVIRONMENT, not target names: `docs-lint.yml` gates every PR and was unmapped, `dashboard-ci` dropped CI's `pnpm link`, and `docs-site-ci` is non-frozen locally because Actions sets `CI=true` |
| H14 | An issue I filed myself has a sound premise | **REFUTED, tick 47** — #1017's stated root cause (a v0.26->v0.27 generator regression) never happened; 54 release tags contain no `SYN_GATEWAY_BIND`. Acting on it would have "restored" a variable that never existed |
| H12 | A gate that passes is a gate that works | **REFUTED, tick 45** — four gates written this week were structurally incapable of failing: `check_test_debt --warn-only`, the scorer's `--rev`, `main() -> 0`, and `grep -q` under `pipefail` returning 141. Each looked identical to a working gate until its hazard was reproduced |
| H5 | Mechanical scoring beats opinion for comparing runs | **supported, and the failure generalises** — the instrument was wrong twice (measured FORMAT not grounding; then scored a stale tree). Tick 18 showed the same class outside the scorer entirely: 4 of 6 wrong claims today were unvalidated API queries. Instruments, not resolutions |

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

### Tick 7 — the release blocker was a clock, not the code

**Symptom:** release PR #999 red — 46 passed, 4 failed. All four were the same
integration test:

    assert _bucket_for_today(buckets).breakdown["output_tokens"] == _TRUE_OUTPUT_TOKENS
    E  assert 0.0 == 13300

**First hypothesis (wrong):** the release broke the cost pipeline. Plausible —
this release is FULL of cost changes (#940, #979, #966), and `0.0` where tokens
should be is exactly what a broken cost projection looks like.

**What actually decided it:** the same commit PASSED at 23:34 UTC and FAILED at
01:48 UTC. Code does not change between runs; the clock does.

**Root cause:** the test inserts rows at `now() - 2 hours` and `now() - 1 hour`,
then queries only TODAY. Run between 00:00 and 02:00 UTC both rows land in
yesterday, today's bucket is empty, and the assertion reads `0.0 == 13300` —
indistinguishable from the production query returning nothing.

**Proved arithmetically rather than by re-running CI**, because at 02:10 UTC the
OLD test also passes — a green re-run would have "confirmed" a fix that had done
nothing:

    run time   now-2h       now-2s
    00:30      YESTERDAY    ok
    01:48      YESTERDAY    ok       <- the observed failure
    02:10      ok           ok       <- now; both pass, proves nothing
    23:34      ok           ok       <- the observed success

    broken window: hours = 2h 00m 00s   seconds = 0h 00m 02s

The model reproduces both observed outcomes, which is what makes it an
explanation rather than a story.

**Also learned:** #1000 shows CI green while "Python Integration Tests:
skipping" — integration runs only on schedule, main pushes, and PRs targeting
`release`. So green on a feature PR is NOT evidence for an integration fix. The
real run happens when #999 picks it up.

**Residue left deliberately:** two seconds either side of midnight still breaks.
Eliminating it needs a future-dated row or a frozen clock; the comment states
the residue rather than implying it is gone.

### Tick 8 — release green; #998's reachable half closed

**Did:** merged #1000 (the heatmap flake). Verified #999 is genuinely green
rather than trusting the badge — PR head `3b4e86e3a484` equals `origin/main`,
and Python Integration Tests **passed after actually running** (1m38s), not
skipped. That check matters: on #1000 the same job reported green while
SKIPPING, because integration only runs on schedule, main pushes, and PRs
targeting `release`.

**Caveat I am keeping honest about:** it is now past 02:00 UTC, so the OLD test
would also pass. This green does not prove the fix. What proves it is the
arithmetic model plus the real-Postgres check run AT 02:13 UTC, inside the
window that broke the original.

**Then #998.** Hypothesis: the fix belongs at the request boundary, not in the
background task.

**Confirmed by the code itself** — `_validate_execution_request` already
carries the comment *"Reject at the boundary so
silent-success-then-BackgroundTask-failure can't happen"* for the repo-identity
check. The pattern was already there and argued for; skills simply were not in
it. That is stronger than my reasoning: someone had already hit this class and
written down the remedy.

Three judgment calls, each recorded because each could be wrong:

- **Reuse the resolver's message verbatim.** It already names the skill, source,
  pinned version and two remedies. A paraphrase drifts from what was actually
  rejected.
- **Catch `SkillError`, not `SkillNotRegistered`.** Catching only the subclass
  from the bug report leaves every sibling on the silent path.
- **Fail-open on the RESOLVER, fail-closed on the REF.** A missing registration
  is a user error and must be reported; a resolver that will not construct is
  ours, and refusing every workflow over it turns a degraded subsystem into a
  total outage. Codex is being asked to argue the other side.

**Mutation-checked four ways**, each caught by the test that should catch it.
The sibling-error test deliberately raises a DIFFERENT `SkillError` subclass
than the bug report, so it cannot pass against a narrower catch.

**Two of my own errors, both caught by gates rather than by me:** I imported
`SkillError` from `_shared` (a deep cross-context import the fitness gate
rejects) when it was already exported publicly; and my replacement error class
was not exported at all and takes two constructor args. Neither would have been
caught by reading.

**Scope held deliberately:** persisting the aggregate before returning 200 is
the general fix and is NOT in this PR. #998 stays open for it. This closes the
reachable case only, and the PR says so.

### Tick 9 — codex dismantled my #998 fix; H2 finally under test

**Hypothesis going in:** #1002 closed #998's reachable case.

**Evidence: wrong on three counts, two of them errors in my REASONING rather
than my code.**

1. **Workflow-scoped skills were never validated.** I passed
   `resolve_for_phase((), phase_refs)` and skipped phases with no phase-level
   refs. Production resolves BOTH scopes together. A workflow whose only
   unregistered skill was workflow-scoped still returned 200 then 404 - the
   reported bug, reachable through a different door.

2. **My fail-open was wrong, and I had argued for it.** I asked codex to argue
   the other side and it was right: the background handler constructs the SAME
   resolver moments later, before persistence, so skipping relocates the failure
   back into the window this exists to close. Nothing retries in between, so the
   200 is not truthful. Now 422 for the caller's error, 503 for ours, with a 10s
   timeout because the resolver reads Postgres and the store sets none.

3. **All six of my tests passed with the CALL SITE deleted.** They drove the
   helper directly - proving the helper worked while the endpoint kept returning
   200. My no-skills test also counted resolve calls rather than FACTORY calls,
   so it passed with the early return deleted.

That third one is the day's recurring failure one level up: I mutation-tested
the HELPER and never the BINDING. A fix is not tested until something asserts
the caller calls it.

Now mutation-checked four ways, each caught by exactly one test.

**Then CI caught a fourth**, which I had missed by running the wrong scope
again: `getattr(workflow, "skills", None)` violates the repo's no-string-keyed-
lookup lint. Worse than stylistic - a rename would have silently yielded an
empty tuple and skipped validation entirely, the same silent-pass class the PR
exists to close. I had run only the new test file, not
`pytest -m unit apps/syn-api/`, which catches it.

**Filed #1003:** GitHub triggers bypass this boundary entirely - they call
`run_workflow()` directly and mark the trigger `dispatched` regardless. Worse
than the HTTP case: no caller holds a response, and the trigger record asserts
success. The unattended path is the one that most needs to fail loudly.

### H2 is finally testable

Registered the six SLP skills against the Mini (`POST /skills/registrations`,
six 201s), cloned at the exact pin `1348146`. The skills run now EXISTS
(`GET /executions/exec-dc01c5b029ec` -> 200) where the pre-registration attempt
returned a permanent 404.

That is also independent confirmation of #998's root cause: registration was the
only variable, and the failure mode was silence rather than an error.

H2 measurement in flight. Baselines to beat:

    v1  3 phases, no skills   $3.3246   13/21 (62%)
    v2  4 phases, no skills   $3.5111    9/12 (75%)

### Tick 10 — H2 measured, and the instrument was measuring the wrong thing

**H2 result** (`exec-dc01c5b029ec`, 4 phases + 6 SLP skills, same #990 task):

| run | cost | citations | GROUNDED | EXACT |
|---|---|---|---|---|
| v1 3ph, no skills | $3.3246 | 21 | 21/21 (100%) | 13/21 (62%) |
| v2 4ph, no skills | $3.5111 | 12 | 12/12 (100%) | 9/12 (75%) |
| **H2 4ph + skills** | **$4.1380** | **6** | **5/6 (83%)** | **0/6 (0%)** |

**H2 is NOT supported.** Skills cost 18% more than v2 and produced fewer
citations, none of them usable as written, and one ambiguous. On this metric,
adding skills made the plan less verifiable.

**But the bigger finding is that my metric was wrong**, and I only saw it
because the result was surprising enough to check.

The scorer reported `0/6 resolve (0%)` for H2 - which reads as fabrication. It
was not: every cited file was REAL, just written as `routes/artifacts.py`
instead of the repo-root-relative path. **The scorer had been measuring
FORMATTING while I described it as measuring grounding**, including in the
decision brief and in H5.

It now reports two numbers:

- **GROUNDED** - the file exists at that line. The trust signal.
- **EXACT** - the path is usable as written. Citation hygiene.

A plan can be 100% grounded and 0% exact. Reporting those as one number told me
a well-grounded plan was fabricating.

**A second defect in the same instrument:** `_shared/value_objects.py` matches
four bounded contexts, and the scorer called that "no such file anywhere" - a
lie about a path whose target exists several times over. Ambiguity is still a
legitimate ding (a reader cannot follow it either) but it is a different
failure, now reported as one.

**Third measurement error of the day, same class:** I first scored against the
wrong worktree, and scores shifted between trees (v2: 12/12 vs 11/12). An
instrument whose reading depends on which checkout you run it from is not
measuring the artifact.

**What this does to the earlier conclusions.** H1 stands - v2 beat v1 on EXACT
(75% vs 62%) and both were 100% grounded, so phase isolation improved hygiene
without harming grounding. But the headline I recorded, "62% -> 75% citation
accuracy", was accuracy of FORMAT, not of fact. Corrected above.

**Priority 4 is now clearly the next experiment**: one prompt line requiring
repo-root-relative paths should move EXACT sharply, and the two-number scorer
can finally tell whether it costs grounding.

### Tick 11 — experiment 4: one prompt line, measured

**Hypothesis (H6, new):** the single cheapest quality win available is a prompt
line requiring repo-root-relative citations. Across three runs EXACT ranged
62% -> 75% -> 0% while GROUNDED stayed 83-100%, so every failure was format,
not fabrication. If the format is the whole problem, saying so should move EXACT
sharply and leave GROUNDED alone.

**Why it is a real experiment and not a guess:** the corrected two-number scorer
can now distinguish the two outcomes. Before this tick it could not - a run
that got worse at formatting and better at grounding would have looked like a
straight regression.

**Method:** `sdlc-research-plan-v3`, identical to v2 in every other respect,
with one section added to all four phase prompts. Same #990 task. Asserted at
build time that all four templates carry it, rather than trusting the edit.

The line names the actual failure rather than stating a rule: it points out
that `_shared/value_objects.py` matches four bounded contexts and identifies
none of them, so a reader cannot follow it and a checker cannot verify it. A
model given the reason has something to generalise from; a model given "use
full paths" has a rule to forget.

**Running:** `exec-efd0d97a0ab7`. Predictions recorded BEFORE the result, so
this cannot be read backwards:

- EXACT should rise well above 75%. If it does not, the format is not something
  a prompt can fix and the scorer should be relaxed instead.
- GROUNDED should stay at or near 100%. If it falls, the instruction traded
  accuracy for tidiness, which would be a bad trade and worth abandoning.
- Cost should be roughly v2's $3.51. A large rise would mean the phases are
  spending tokens on path bookkeeping rather than thinking.

### Tick 12 — codex pass 2 found a credential leak in my own fix

**Hypothesis:** pass 1's fixes were complete and #1002 was mergeable.

**Wrong on three more counts, one of them a security defect I introduced.**

1. **The 503 reflected the exception text.** I wrote
   `detail=f"could not verify declared skills: {exc}"`. Infrastructure failure
   here is usually a database error, and those carry a DSN - user, host,
   database, sometimes the password. I put an arbitrary internal exception into
   an HTTP response body while trying to make a failure *more* legible. The
   detail is now constant; the cause goes to the log.

2. **The timeout did not enclose service construction.** The factory await sat
   OUTSIDE `asyncio.timeout`, so a hang inside it was unbounded - and the
   factory is precisely where a pool acquire or DNS lookup would appear. Cheap
   today; the boundary is the point.

3. **The error named the wrong phase.** I caught `SkillError` outside the loop
   and guessed afterwards - "the first phase with any skill". With a failure in
   the second phase that blames the first, pointing whoever reads it at code
   that is fine. Now caught per ref with the declaring phase.

My existing tests could not have caught any of these: they asserted a status
code and the presence of a skill name, and none of that changes when the body
carries a password or when a hang is unbounded. **Passing tests were evidence
about the wrong properties.**

**A test-double lesson:** the ref doubles were bare strings. They passed while
the code only COUNTED refs and broke the moment it read their fields. A double
that cannot be used the way the real object is used tests less than it appears
to - and the gap is invisible until the production code changes.

All three mutation-checked, each caught by exactly one test.

**Fitness then caught the shape:** the function hit 17 cognitive / 14 cyclomatic
after the changes. Extracted `_unique_skill_refs` - collecting refs and talking
to a resolver are different jobs, and the split is also where the dedupe
belongs.

### Tick 13 — #1002 merged; v3 costing more than predicted

**Merged #1002** after two codex passes with every finding cleared and CI green.
Verified live on `origin/main` rather than assuming the merge implies it: the
call site and the definition are both present.

**#999 re-ran automatically** — its head IS main, so merging #1002 updated it.
34 checks re-running, none failing so far. Worth noting as a property: a release
PR from `main` cannot go stale, but it also re-runs the whole gate on every
merge, which is why "green" has to be re-checked against the head SHA each time
rather than remembered.

**v3 (experiment 4) is mid-flight and already contradicts one prediction.**

I predicted cost near v2's $3.51. Three phases in, it is at **$4.60** — above
v2 and above H2's $4.14 total. Recording this BEFORE the final number, because
the temptation once EXACT improves will be to treat the cost as acceptable in
hindsight.

If EXACT rises sharply, the honest framing is a TRADE - better citations for
~30% more spend - not a free win. If EXACT does not rise, the instruction cost
money and bought nothing, and should be reverted rather than kept for tidiness.

The prediction that cost would stay flat was based on nothing: a prompt section
adds input tokens to every phase and asks the model to be more careful about
paths, and both cost tokens. I should have predicted an increase and estimated
its size.

### Tick 14 — H6 strongly supported, after my scorer nearly buried it

**Result, scored against a clean checkout of `origin/main`:**

| run | cost | citations | GROUNDED | EXACT |
|---|---|---|---|---|
| v1 3ph | $3.3246 | 21 | 21/21 (100%) | 13/21 (62%) |
| v2 4ph | $3.5111 | 12 | 12/12 (100%) | 9/12 (75%) |
| H2 4ph + skills | $4.1380 | 6 | 5/6 (83%) | 0/6 (0%) |
| **v3 4ph + format rule** | **$6.4996** | **55** | **54/55 (98%)** | **54/55 (98%)** |

**H6 is strongly supported.** One prompt section took EXACT from 75% to 98% and
- unexpectedly - took citation COUNT from 12 to 55 while holding grounding at
98%. The instruction did not merely reformat citations, it produced four times
as many verifiable ones. Plausibly because a model told its citations will be
checked starts citing things it can defend.

**Cost is the trade: $6.50 against v2's $3.51, +85%.** Recorded as a trade, per
the framing fixed in advance. Per verifiable citation it is cheaper - $0.39/exact
citation for v2 versus $0.12 for v3 - but the absolute number is what a budget
sees.

### I nearly reverted it on a false negative

My first score was **GROUNDED 39/55 (71%)** with all 16 failures reading
"line is past end of file". By my own pre-registered criterion - "if GROUNDED
falls, the instruction traded accuracy for tidiness and is worth abandoning" -
that meant revert.

**The scorer was pointed at a checkout 31 commits behind main.** The main
working directory sits on `feat/workflow-validation-suite`, not `main`:

    artifact_query_service.py   my tree 127 lines   origin/main 186   cited :154-186
    value_objects.py            my tree  81 lines   origin/main 102   cited  :85-102

Every "past end of file" citation was correct against the tree the agent
actually read. Re-scored against a clean `origin/main` worktree: 54/55.

**This is my fourth measurement error today and the most consequential.** The
others cost a few minutes; this one would have discarded the best result of the
day and recorded a false conclusion in a document meant for decisions. It only
surfaced because the failure mode was suspiciously uniform - sixteen citations
failing the same way, none fabricated - which is not what real hallucination
looks like.

**Structural fix needed, not vigilance:** the scorer must take the commit the
plan was written against and score against THAT. Scoring a plan about a moving
repo with whatever happens to be checked out locally is not a measurement.
Filed as a follow-up.

### Tick 15 — fixed the instrument structurally, not by being careful

**Hypothesis:** the near-miss in tick 14 was a discipline failure, so the fix is
to remember to check the tree.

**Rejected.** I had already resolved to "verify your own measurement" three
times today and still walked into it a fourth. A rule I keep breaking is not a
control. The scorer had to stop depending on ambient state.

Two changes:

1. **`--rev`** reads blobs via `git show <rev>:<path>`, so the answer does not
   depend on what is checked out. Verified from the SAME stale directory that
   produced the false 71%: with `--rev origin/main` it reports 98%.

2. **A banner on every run**, stating the tree and warning when it is behind:

       scoring against: .../syntropic137 @ feat/workflow-validation-suite (27926d84)
         ** 31 COMMITS BEHIND origin/main - citations may read as out of range **

   The failure was silent before. Now the thing that misled me is the first line
   of output.

Control preserved: a fabricated file still fails at a revision, so the fix did
not make the scorer permissive.

**Filed #1004** — the deeper gap. An execution records the repo URL but NOT the
commit it cloned, so no artifact from any run can be verified against the code
it actually saw. The workspace clones at a specific commit and discards the
value. Without it, "the same task" across two runs silently means different
code, which undermines every comparison recorded in this log.

That is the honest limit on today's numbers: v1, v2, H2 and v3 ran hours apart
against a moving `main`. I have been treating the input as constant and cannot
prove it was.

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

### Tick 16 — codex found my fix did nothing, and my tests could not have noticed

**Worked:** #997, the flat phase alias diverging between the live and cold
paths. PR #1005, plus issue #1006 for what it does not close.

**Premise check first.** #997 was written by codex from a review, so I verified
both halves before building on it: `postgres_query_builder.py` does emit
`ORDER BY updated_at DESC` for an unordered query, and `ArtifactCollector`
does take the first collected file. Both true. (#989 cost a full workflow run
this morning because nobody did this.)

**Hypothesis:** persisting an explicit primary removes ordering from the
selection, so live and cold agree. Implemented it, wrote five tests, and
mutation-tested four ways — each mutation killed a specific named test.

**Codex found the fix was inert.** `on_artifact_created` never copied
`is_primary_deliverable` into the read model. Every projected row read back as
primary, so production still fell back to row order. The change did nothing.

The reason my tests missed it is the part worth keeping: **all five
hand-constructed an `ArtifactSummary` and stopped one hop short of the
projection — the exact boundary where it broke.** Four green mutations proved
the ranking logic was pinned; they proved nothing about whether the value
reaches it. Mutation testing measures the tests you wrote, not the ones you
didn't.

Codex also killed a fifth mutation I had not tried — `stamp = artifact.id`
survived everything, because my expected artifact was always named `art-a` and
id order accidentally agreed with creation order. And it produced a concrete
counterexample to the timestamp tiebreak: ISO strings do not sort
chronologically, so `T10:00:00+02:00` (08:00Z) sorted AFTER
`T09:00:00+00:00` (09:00Z) because `"10" > "09"`.

Fixed all four, re-mutated: the projection line, the id ranking and the string
comparison now each fail specific named tests. Deferred two findings to #1006 —
retries and `collect_partial` can create multiple primaries, and
`get_files_for_phase_injection` has the same row-order bug. Both need selection
to come from `ArtifactsCollectedForPhaseEvent.artifact_ids`, which is a design
change, not a patch.

**A measurement error I caught on myself, and one I did not.** I copied my
changed files wholesale from the dev branch into a fresh worktree off `main`.
Two tests failed there that had passed locally. That could have read as
flakiness; it was not — my dev branch predates #988, so the copy silently
reverted 209 lines of `ArtifactCollector` and 69 of the query service. Because
the failure was loud and specific I caught it, reset, and reapplied every edit
against main's actual content. This is the same stale-tree error as tick 14,
and this time the tests caught it rather than my judgement.

The one I did not catch on my own: I measured "1,045 tests never run in CI"
and started to treat it as a finding. It was real in the dev tree and false on
`main` — `test_artifact_collector.py` already carries a module-level
`pytestmark = pytest.mark.unit` there. **Third time today I have measured the
wrong tree.** The `--rev` flag I added in tick 15 fixed this for the citation
scorer specifically; the general habit is untouched, because the fix was
instrument-shaped and the habit is not.

**Evidence:** `syn-domain` 1737 passed, adapters + apps 1513 passed, ruff and
pyright clean, untyped-dicts ratchet held at 391 by typing the new helper
rather than raising the budget.

### Tick 17 — codex pass 2: my fix made one case worse, and my new test could not fail

**Worked:** codex pass 2 on #1005 (the second and final allowed pass), then
fixed what it found. Pushed 4b074e8f.

**Hypothesis going in:** pass 2 would confirm the four pass-1 fixes and find
nothing structural, because I had mutation-tested each one.

**Contradicted, on the part I did not think to check.** The pass-1 fix made one
production case WORSE than before. I had taught the flat alias to rank
candidates, but left `get_files_for_phase_injection` returning raw projection
order — and `_tree_files` dedups first-wins. So with a duplicated `source_path`
the alias resolved to the earliest primary while the tree kept the newest row:
**a restart could inject two different versions of the same deliverable**, one
at `<phase-id>.md` and another at `<phase-id>/<source_path>`. Before my branch
both read newest-first and at least agreed.

I reproduced it before fixing — both new consistency tests failed against the
previous commit. That is the difference between accepting a finding and
verifying one.

The reasoning error is worth naming: I treated "the tree path" as deferred
scope because codex had filed it under a deferred finding. But two readers of
one phase output disagreeing IS the defect #997 describes. I had drawn the
scope boundary around the *finding number* rather than around the *bug class*,
which is precisely the carve-out I am supposed to refuse.

**And the second tautological test in two ticks.** I added a strict-boolean
read because `bool("false")` is True, then tested it by asserting `"false"`
reads as True — which the strict AND the coercing implementation both satisfy.
Mutation killed nothing. Rewritten against `0`, where the two genuinely
differ, and the mutation now fails it.

Both tautologies had the same shape: **I picked an input where the two
candidate behaviours happen to agree.** Mutation testing catches this, which is
why it is not optional — but only if the mutation is the one that matters. A
test that cannot distinguish the fix from its absence is decoration no matter
how green it is.

**Accepted without changing:** the VERSION 4->5 bump does rebuild (codex traced
the coordinator deleting rows + checkpoint and replaying from zero), though
there is a visibility window because startup does not wait for catch-up. That
is a property of every projection bump in this repo, not something this PR
introduces.

**Standing:** #1005 has had its two codex passes with findings cleared; #999
remains green at 50 checks and is the owner's to merge.

### Tick 17b — #1005 merged

All 15 checks green against an unmoved base (`origin/main` still `eb32bc1a`,
0 commits since I branched — so the green was measured against what it will
actually merge into, not a stale one). Merged as `b2aa7466` with a merge
commit; #997 auto-closed.

**#999 is now the ONLY open PR**, still green at 50 checks, and stays the
owner's call — merging it publishes to npm and GHCR, tags, and cuts a public
release.

### Tick 18 — planning #1004 through Syntropic; five measurement errors in one day

**Ran through Syntropic on the Mini**, not locally: `exec-167fbe65f189`,
workflow `sdlc-research-plan-v3` (the 98%-EXACT variant), task = design how an
execution records the commit SHA of every repo it cloned (#1004). Running at
last check.

**Why #1004 and not #1006.** #1004 is the gap that limits every measurement in
this log: no artifact from any run can be checked against the tree the agent
read. I picked it, then checked whether it was tick-sized. It is not —
`WorkspaceServicePort.clone` is **dead code** (no implementation, no callers);
the real clone is a generated shell script in `setup_phase_secrets.py`, and
there is no structured channel back from setup to the host. So it spans script
-> transport -> domain event -> projection -> API. That is a planning job, which
is exactly what the owner asked to route through Syntropic. Dispatched rather
than hand-rolled.

**Premise verified live, not from my own issue text.** `GET
/api/v1/executions/exec-efd0d97a0ab7` really does return
`repos: ["https://github.com/syntropic137/syntropic137"]` with no SHA.

**Then I made three false findings in a row, all my own query errors.**

1. "The SDLC workflows are not installed on the Mini." Wrong — I filtered on
   `workflow_id`, which the list response does not carry. They were all there.
2. "`workflow_id` is None for every workflow — the list returns null ids."
   Wrong — the field is named `id` on the list.
3. "`phase_count` is 0 for everything." Wrong — I read a `phases` key that does
   not exist on a summary. `phase_count` is correct (v3 reports 4, matching
   detail).

Each dissolved the moment I printed the raw keys instead of my filtered view.

**That is five measurement errors today** (the 31-commit-stale scorer, the
wrong-tree test census, and these three). Every one has the same shape: **I
asserted from a query or scope I had not validated, and the failure mode was a
silent empty result that reads as a finding.** Tick 15 fixed one instrument;
the habit is untouched, because the fix was instrument-shaped and the habit is
not. The generalisable control is cheap and I keep skipping it: **print the raw
shape once before filtering it.**

**One real finding survived** and became #1007: workflow identity is `id` on the
list endpoint and `workflow_id` on detail and execution. AGENTS.md explicitly
requires these to match across layers. The cost is exactly what bit me — reading
`workflow_id` off a list item yields None silently, so a client dispatches on
nothing and gets "no such workflow" instead of "wrong field name". An agent is
the stated acceptance case for this API, and the natural list-then-execute loop
does not compose today.

### Tick 18b — I retracted my own issue an hour after filing it, then built the control

**#1007 closed as invalid.** I filed it claiming workflow identity is `id` on
the list endpoint and `workflow_id` on detail and execution. Checked against the
live API afterwards:

| endpoint | field | value |
|---|---|---|
| `GET /workflows` | `id` | `sdlc-research-plan-v3` |
| `GET /workflows/{id}` | `id` | `sdlc-research-plan-v3` |
| `GET /executions/{id}` | `workflow_id` | `sdlc-research-plan-v3` |

Workflows expose their own identity as `id` on **both** list and detail; an
execution references a foreign workflow as `workflow_id`. That is ordinary REST
convention, not the cross-layer drift AGENTS.md prohibits. I had inferred the
detail shape from line numbers in `queries.py` — two classes there both declare
`id: str` and others nearby declare `workflow_id` — instead of reading the
response that was already sitting on disk.

**Sixth error today, and the second premise I have had to retract after #989.**
I made it in the same tick where I wrote "print the raw shape once before
filtering" as the lesson.

**So I stopped resolving and built the instrument.** `scripts/api_shape.py`
prints a response's real key shape, and `--find <value>` answers the question I
kept getting wrong: not "is it under the key I assumed?" but "which key is it
actually under?"

Exit codes are load-bearing because the failure mode being guarded is silence:
`0` found, `1` absent, `2` not JSON. That third one catches a real trap on this
stack — the dashboard SPA catch-all answers unknown paths with **200 and HTML**,
which is why fetching `/openapi.json` from the Mini earlier this tick looked
like a server problem when the path was simply wrong.

Verified against the live Mini, including the negative control: a genuinely
absent value reports absent and exits 1. Each of today's four API errors would
have been one command.

The pattern worth keeping: **tick 15 fixed `--rev` on the citation scorer and I
treated the class as closed.** It was not — the same failure was waiting in a
completely different instrument. A fix that is instrument-shaped closes exactly
one instrument.

**Meanwhile** `exec-167fbe65f189` (the #1004 plan) is still running on the Mini,
phase 1 of 4, $2.21.

### Tick 18c — PR #1008 opens the branch that has been sitting unmerged all day

25 commits, 1888 lines, **zero deletions**: the four-phase SDLC workflow, the
citation scorer, `api_shape.py`, the decision brief, and this log. `just
preflight` green — every static CI gate.

**Checked coverage rather than assuming it.** #986 says packaged workflows go
unvalidated, so before opening the PR I asked whether the repo's own gate
actually sees mine. It does: `workflows/sdlc/research-plan/workflow.yaml` is in
`check_workflow_definitions.py`'s scanned set and passes.

**Seventh instance of the same error, caught this time.** My first check printed
all 20 workflow files as "MINE", because I filtered on `'sdlc' in str(path)` and
the *worktree directory* is named `20260829_sdlc-workflows` — so every absolute
path matched. This is verbatim the trap already recorded in
`patterns_tmp_path_named_after_test`: a substring assertion over a captured path
matching the harness's own name. I caught it by reading the output instead of
the conclusion, which is the whole point of the tick-18b instrument.

**What the PR does NOT claim.** The four experiment results are stated with
their limit attached: the runs are hours apart against a moving `main`, and
because of #1004 no execution records the commit it cloned, so I cannot prove
the input was constant across comparisons. H6's effect (EXACT 75% -> 98%,
citations 12 -> 55) is large enough that drift is an implausible explanation;
H1 and H2 are weaker and genuinely rest on an assumption I cannot check. Said
so in the PR body rather than presenting four clean rows.

**Standing:** #999 green and unmerged (owner's). #1008 open. #1005 merged.
`exec-167fbe65f189` still running on the Mini at $5.44, phase 3 of 4.

### Tick 19 — codex blocked my PR because my measuring instrument fails toward "looks good"

**Reviewed the scorer, not the code.** `scripts/score_plan_citations.py` produced
every experimental number in this log, so if it is wrong every conclusion here
is wrong. I asked codex to treat it as an instrument whose calibration is the
deliverable. Verdict: **not calibrated well enough to support the published
conclusions.** Blocked.

**The critical defect, verified by me before fixing:**

| input | scored |
|---|---|
| `--rev definitely-no-such-rev` | **100%** |
| a file absent at `origin/main` but present locally | **100%** |

Every nonzero `git show rev:path` became `None`, and `verify()` then continued
with the working tree. So the flag silently degraded to exactly the behaviour it
was added to prevent.

**This is worse than the bug it replaced, and the reason is the lesson.** Tick 15
added `--rev` precisely to stop scoring against a stale checkout. I verified it
on the path where the file EXISTS at the revision — which works, and gave the
71% -> 98% correction I was pleased with. **I never tested the path where the
file does not exist at the revision, which is the fabrication case the flag
exists to catch.** I then published four results on the strength of that
half-verification.

That is the same shape as the tautological tests in ticks 16 and 17: I confirmed
the behaviour on an input where the fix and its absence agree, and called it
verified.

**Second finding, an overclaim I repeated all day:** GROUNDED proves an ADDRESS
resolves. It does not prove the cited lines support the claim attached to them —
any invented claim followed by a real `file:line` scored "grounded". Renamed
**RESOLVES**, with the limitation printed on every run. Calling it "the trust
signal" in this log was wrong.

**Also fixed:** unvalidated ranges (`10-2` and `1-0` scored valid, and `label`
rendered `:1-0` as `:1` because zero is falsey); `./x.py` and `../outside/x.py`
scored EXACT (`PurePosixPath` normalizes `./x` to `x`, so the segment check has
to run on the raw string); `git show HEAD:scripts` counted a directory listing
as ~49 lines; line counting lost the final line of a file with no trailing
newline and could crash on a binary blob.

Each verified failing before and passing after.

**Consequence: the 62% / 75% / 83% / 98% table is withdrawn.** The artifacts are
on the Mini and re-scoring is pending. H1 and H2 are marked withdrawn above
rather than quietly left standing.

**One result re-established on the corrected instrument.** A fresh v3 run
planning #1004 (`exec-167fbe65f189`, $8.40, 4 phases, run on the Mini):

```
RESOLVES  37/37 (100%)   EXACT  37/37 (100%)
```

First number today measured by an instrument that refuses to fail toward good.

**And the run corrected me.** My task prompt asserted the dead code was
`WorkspaceServicePort.clone`. The plan found no such class and identified
`GitConfigurationPort.clone` (`ports.py:220,235-244`) instead — an error in MY
premise, caught by the workflow rather than by me. Worth recording, because I
have spent all day writing about checking premises.

**Still outstanding from the review:** fenced code blocks are counted as
citations; `path:1` and `path:1-1` count twice; and the PR claim that every
phase gets a scoped toolset is **false** — the codex review phase has no
allowlist and runs `--sandbox danger-full-access`.

### Tick 20 — I withdrew four conclusions that turn out to have been right

Re-fetched the final artifact of all five runs from the Mini and re-scored every
one on the corrected, fail-closed instrument, all against `origin/main`.

| run | cost | cites | RESOLVES | EXACT | broken scorer said |
|---|---|---|---|---|---|
| v1, 3 phases | $3.32 | 21 | 100% | **62%** | 100% / 62% |
| v2, 4 phases | $3.51 | 12 | 100% | **75%** | 100% / 75% |
| v2 + SLP skills | $4.14 | 6 | 83% | **0%** | 83% / 0% |
| v3, citation rule | $6.50 | 55 | 100% | **100%** | 98% / 98% |
| v3 on #1004 | $8.40 | 37 | 100% | **100%** | — |

**Not one comparison moved.** Four numbers identical; v3 improved 98% -> 100%.

**Why the defects did not bite here, stated so the next reader can check me.**
The fail-toward-good path only triggers when a cited file is ABSENT at the
scored revision. These plans cite long-standing repository files that exist in
both the working tree and at `origin/main`, so the broken fallback returned the
same answer the correct path returns. The bug was real and severe; this
particular corpus just never exercised it. My own probe file did, which is how
codex demonstrated it.

**And I was wrong about which reading was fragile.** In tick 19 I wrote that
H2's 0% EXACT was "the LEAST likely to survive, since EXACT wrongly accepted
`./` paths" — reasoning that a stricter EXACT could only lower scores, so a 0%
had nowhere to go but up. It survived completely unchanged. The prediction was
backwards: tightening EXACT cannot raise a score, so 0% was the ONE reading
that was already safe. I had the direction of the correction inverted while
writing about being careful with directions.

**H1 and H2 restored** with their original verdicts. **H6 is now n=2** on the
corrected instrument.

**The honest summary of ticks 19-20:** the withdrawal was correct procedure and
I would do it again — I could not know the numbers survived without
re-measuring, and publishing on a demonstrably broken instrument is not
defensible whatever the numbers happen to say. But the outcome is that the
instrument was broken in a way that did not touch these results, and saying
"withdrawn" was cheap while saying "re-measured, unchanged" is what actually
settles it. Withdrawal without re-measurement would have been theatre.

### Tick 21 — the obvious fix deleted every citation; and codex was half wrong

Closed the last two scorer findings and corrected the tool-scoping docs.

**Fenced examples and duplicate spans:** a plan that DEMONSTRATES the citation
format inside a fence was scored as having made that citation, and `x.py:5` /
`x.py:5-5` counted as two locations. Both fixed, both mutation-verified.

**The fence fix, done the obvious way, was a disaster.** I followed the review's
"exclude code blocks" wording and blanked inline `backticked` spans too. That
deleted **every real citation in every plan measured so far** — these plans
write citations as `path/to/file.py:12-30`, because that is simply how markdown
names a file. All five runs scored NO CITATIONS. Caught in one command by
re-scoring instead of assuming. Fenced blocks are where a document demonstrates
its format; inline code is where it names things.

**Codex was half wrong, and acting on it would have made an accurate doc
wrong.** Finding 6 said my comments were stale because "current wiring uses the
restrictive `--tools`". `--allowedTools` is the ONLY tool flag emitted anywhere
in production code (`_wiring.py:285`); `--tools` appears nowhere. My comment was
right. I only caught it because I opened the file to edit it.

That is the mirror of the tick-16 lesson. There I under-trusted nothing and
accepted a finding wholesale; the correct posture is the same in both
directions — **a review finding is a hypothesis until something runs.**

**What WAS true, verified myself:** the codex phase has no tool enforcement and
cannot be given any — `_build_codex_command` hardcodes `--sandbox
danger-full-access` and takes only a prompt and a model. Filed **#1009**. The
container is still the isolation boundary, so this is not host security; the
cost is review independence, since the reviewer can rewrite the document it was
asked to critique and the artifact collector will pick up the rewrite.

**Re-scored all five runs after both fixes: every number unchanged.**

### Tick 22 — I used a stale tree to publicly contradict a correct review

Codex pass 2 on #1008 blocked again. The finding that matters is about me.

In pass 1 codex said my docs were stale because "current wiring uses the
restrictive `--tools`". I disputed it, grepped, found `--allowedTools`, and
wrote in a commit message, a log entry AND a PR comment that codex was wrong.

**It was not wrong.** `origin/main:297` emits `--tools` and #964 is CLOSED. My
grep ran in a working directory **35 commits behind main** — the same stale-tree
error as ticks 14 and 18, the third time today, and the first time I used it to
contradict someone who was right.

The asymmetry is worth naming. In tick 16 I accepted a codex finding wholesale
and it was correct. In tick 21 I rejected one and was wrong. Neither posture is
the lesson; **the lesson is that a review finding is a hypothesis and so is my
rebuttal, and the rebuttal needs the same execution the finding does.** I ran a
grep, which felt like executing. It was executing against the wrong tree.

**Consequence, and it cuts in a good direction for once:** per-phase tool
scoping IS enforced for the claude phases via a comma-joined `--tools` flag
governing availability. My README had claimed it was declared-but-unenforced,
so my "correction" preserved a falsehood I had inherited. Docs now written from
verified behaviour. #1009 (codex phase unrestricted) stands and was always the
true half.

**Scorer, also from pass 2:** the regex matched from the middle of an invalid
token and stopped before invalid trailing text, so `/src/x.py:1`,
`bad\src/x.py:1` and `src/x.py:1-junk` all cropped to `src/x.py:1` and scored
EXACT. Fail-toward-good again. Lookbehind + lookahead now refuse them, and I
checked the other direction so real citations still extract.

**Committed the regression tests this script has never had.** 26 of them, one
per defect. Codex was right that every verification so far lived in /tmp probes
that vanished while the numbers were being published.

**Mutation testing found a hole in my own new tests.** Six mutations; the first
pass killed five. Reverting the range guard inside `in_range` killed NOTHING,
because the tests exercised `well_formed` and `in_range` separately and nothing
asserted that a malformed span addresses nothing. Same shape as the tick-16 and
tick-17 tautologies — found this time by the discipline rather than by a
reviewer, which is the first time today that has happened.

**Re-scored all five runs after every change: unchanged.**

### Tick 23 — merged main into the PR before trusting its green

#1008 had both codex passes done, findings cleared, 26 checks green, and
`MERGEABLE / CLEAN`. Under the standing rule that is a merge.

**It was 4 commits behind main, so the green measured a stale base.**
`MERGEABLE / CLEAN` describes a textual merge, not a tested one. Merged
`origin/main` in (merge, never rebase — the 4 commits were my own #1005 work),
re-ran every gate on the result, and pushed so CI re-runs against a base that
is `behind: 0`.

Local on the merged tree: preflight exit 0, syn-domain 1742 passed,
adapters + apps 1513 passed, scorer tests 26 passed.

**And I closed the tick-22 loop honestly.** Having been wrong about `--tools`
because I grepped a 35-commit-stale tree, I re-ran that exact grep from the
now-current worktree before letting the correction stand:

```
297:        cmd.extend(["--tools", ",".join(phase.agent_config.allowed_tools)])
```

`--allowedTools` is not emitted. Codex was right, my correction of my
correction is right, and this time the tree it was measured in is stated.

That is the whole discipline in one line: **the same command, run in a tree
whose currency I checked first.** Three of today's eight errors would not have
happened if I had done that by default rather than after being caught.

Waiting on CI before merging. Not merging #999 — that remains the owner's.

### Tick 23b — #1008 merged

All checks complete, 0 failing, measured against a base that was `behind: 0`
after merging main in. Merged as `ba28a4b2`. On `main` now: the four-phase SDLC
workflow, the citation scorer with its 26 regression tests, `api_shape.py`, the
decision brief, and this log.

**#999 is again the only open PR** — 50 checks green, and merging it is the
publish (npm, GHCR, tag, GitHub Release), so it stays the owner's call.

This log continues on `docs/dogfood-log-continued`, since its original branch
is now merged.

### Tick 24 — #1009 planning dispatched through Syntropic (n=3 for H6)

All five listed priorities are closed, so the work moved to the open issues.
Picked **#1009** (every codex phase runs `--sandbox danger-full-access`; a
workflow cannot make a review phase read-only) because I filed AND verified it
this session, and because it is the one open issue that degrades the SDLC
workflow itself: the cross-model review phase can write to the workspace whose
artifacts are collected, so the reviewer can rewrite what it was asked to
critique.

**Ran it through the platform, not by hand** — `exec-218c408bb916`, workflow
`sdlc-research-plan-v3`, on the Mini. That is the orchestration path the owner
asked for, and it is the third v3 run, so it also extends H6 from n=2 to n=3.

**Hypothesis being tested by the prompt itself:** I handed the workflow a
PRE-VERIFIED premise this time — four facts I had checked directly, each with a
file and line — and explicitly invited it to contradict any of them. The
previous run (#1004) corrected an error in my prompt unprompted, which is
evidence the research phase does not simply accept what it is told. Stating the
premise as checkable rather than as background is the variable.

The prompt also states plainly what the issue is NOT: the container is the
isolation boundary, so this is not host security. Every previous run that went
wrong went wrong on a premise, so being precise about the *shape* of the problem
is cheap insurance.

Running. Score with `scripts/score_plan_citations.py --rev origin/main` when it
lands — now the merged, fail-closed version with its 26 regression tests behind
it, rather than the one that scored an invalid revision at 100%.

### Tick 24b — the tool I built to stop silent-absence had silent-absence

While the #1009 plan runs, closed the outstanding `api_shape.py` findings.
**PR #1010.**

This is the sharpest finding of the session. I built that script in tick 18b
*specifically* because four of my wrong claims were "read a field the response
does not carry, get None, report the silence as a finding". Codex then found
the script did exactly that: `describe()` inspected only element `[0]` of a
list, so a field on later elements was missing from the output and the command
still exited 0.

Reproduced before fixing: `[{"first_only": 1}, {"later_only": 2}]` printed only
`first_only`, and `later_only` was not findable either, because `find_value()`
searched values but never KEYS while reporting "does not appear anywhere".

**The lesson is not "be more careful writing tools".** It is that an instrument
built in reaction to a failure mode inherits that failure mode unless something
tests for it. I wrote the tool AND the docstring explaining the exact bug it
prevents, and still shipped the bug, because I verified it on a homogeneous
list where the defect is invisible. That is the tautological-input mistake from
ticks 16, 17 and 21 for the fourth time — the same shape, in the artifact
designed to prevent the shape.

Fixes: every element summarized with `[in n/N]` on non-universal keys (the
count IS the signal — without it the output still reads as "these are the
fields"); keys searched as well as values; `--at` applied before `--find`
rather than ignored when it is present; `--find-exact` added because substring
search reports `foo` present when only `foobar` exists.

Regression tests added — this script lacked them too, same gap as the scorer.
Mutation-verified four ways, all killed. Negative controls included, so a
`find()` returning everything would not pass.

**Meanwhile** `exec-218c408bb916` (the #1009 plan) is still in phase 1 on the
Mini at $0.89.

### Tick 24c — my fix for the silent-absence bug introduced a different silent-absence bug

Codex reviewed #1010 and blocked it. The headline: **my fix was worse than what
it replaced.**

`_describe_list` unioned only the IMMEDIATE keys of direct dict elements and
never recursed. For `{"rows": [{"meta": {"visible": 1}}, {"meta": {"hidden": 2}}]}`
the old element-[0] version printed `visible`; mine printed `meta: object[1]`
and nothing else. I traded depth for breadth and **lost a field the previous
version showed**, in the one script whose entire purpose is not hiding fields.

Verified both behaviours side by side before changing anything, by running the
old version out of `git show origin/main`.

**Second time today a fix of mine made something worse.** The other was #997:
I taught the flat alias to rank candidates and left the tree path on raw row
order, so the two cold readers disagreed where they had previously agreed. Same
shape both times: **I fixed the case in front of me without asking what the
previous behaviour was good at.** A change is only an improvement if it
dominates; otherwise it is a trade, and a trade has to be argued rather than
assumed.

Fixed with a recursive merge, verified against every payload the review gave —
nested objects, lists of lists, a list sibling of a dict (handling dicts used to
`return` early and skip them), and the `[in n/N]` denominator counting only
dicts instead of the list length.

Also, from the same review: `--find`/`--find-exact` were not mutually exclusive
so supplying both silently answered one; needle and `--at` used truthiness, so
`--find-exact ""` printed the shape and exited 0 without searching; and
transport/decode failures could escape as exit 1, which is indistinguishable
from "looked and it is absent".

**And a third instance of this file containing the exact bug it exists to
prevent:** searching `str(value)` meant a caller typing `null` or `true` — the
JSON spellings that were actually in the response — got NOT FOUND for a value
that is present. Both spellings now match.

**`main()` had no coverage at all**, which is why codex's fifth mutation
(deleting the whole `--at` fix) survived my first suite. And it found a test of
mine that passed for the wrong reason: asserting output was non-empty, which
`describe()` satisfies before the list walker runs, so it passed with the walker
gutted. 28 tests now, mutation-verified six ways, all killed.

**Meanwhile** `exec-218c408bb916` reached phase 4 of 4 at $3.57 — the codex
review phase again cost about $0.56, roughly a sixth of the claude phases.

### Tick 25 — third consecutive 100/100, and my cost speculation was wrong

`exec-218c408bb916` (#1009 plan) completed on the Mini. Scored on the merged,
fail-closed instrument against `origin/main`:

```
RESOLVES  51/51 (100%)   EXACT  51/51 (100%)
```

**H6 is now n=3**, all three v3 runs at 100/100 on both metrics.

**The plan found something I did not know.** I told it `AgentConfiguration` was
the phase config; it found there are **two hand-synchronized copies** —
`aggregate_execution/value_objects.py:55-99` and
`_shared/ExecutionValueObjects.py:34-77` — each carrying a comment telling the
reader to keep it in sync with the other, and it worked out which one `_wiring`
actually imports. That is the second consecutive run where the research phase
corrected or extended my premise rather than accepting it.

**And it contradicted me mid-tick.** When the plan phase came in at $0.52
against $2.66 for the #1004 run, I said in the tick report that the
pre-verified premise "may be reducing discovery work". The completed breakdown
says otherwise:

| phase | #1004 | #1009 | delta |
|---|---|---|---|
| research | 2.21 | 2.50 | +0.29 |
| plan | 2.66 | **0.52** | **-2.14** |
| cross-model-review | 0.57 | 0.55 | -0.02 |
| revise | 2.96 | **4.58** | **+1.62** |
| **TOTAL** | **8.40** | **8.15** | **-0.25** |

The premise did not reduce cost. It **moved** cost — out of planning and into
revision — for a net difference of 25 cents, which is noise at n=1. I had a
partial number and narrated a mechanism from it; the whole number says
something different. Same error shape as the rest of today, just cheaper: a
conclusion drawn before the measurement finished.

Worth noting separately: the **codex review phase costs about $0.55 in both
runs**, roughly a sixth of a claude phase, while H3 says it is the phase that
has caught the most real defects. That is the best cost-to-value ratio in the
whole workflow, and it is stable across runs.

### Tick 26 — a 100/100 plan that would have shipped privilege escalation

Merged **#1010** (16 checks green, `behind main: 0`, two codex passes cleared).
#999 is again the only open PR.

Then, before executing the #1009 plan, I put the FINAL revised plan through an
independent codex review — because a citation score measures whether addresses
resolve, not whether claims are true, and I had just spent a tick establishing
exactly that distinction. Verdict: **not ready**, and the workflow's own
internal review phase was insufficient.

**The finding that matters: the fix would have been privilege escalation.**
The plan asserts that a read-only claude phase whose declared tools intersect
to nothing yields `--tools ""`. I checked the code myself:

```python
if phase.agent_config.allowed_tools:
    cmd.extend(["--tools", ",".join(phase.agent_config.allowed_tools)])
```

An empty tuple is falsy, so `--tools` is **omitted** and every tool stays
available. A phase declaring `allowed_tools: [Bash]` + `read_only` would get
MORE access than one declaring nothing — in the feature whose entire purpose is
restricting access.

**And the revise phase overruled a correct blocker with a false premise.** The
internal codex phase raised the agentic-primitives boundary. Revise rejected it
because "the submodule is unpopulated". It is not — `harnesses/claude` and
`harnesses/codex` are both there at `276eec0ac231`. Verified directly.

**H7, refuted on first test: a 100% citation score does not indicate a correct
plan.** RESOLVES 51/51, EXACT 51/51, and still not executable. The central
claim's citation resolves *perfectly* — real file, real lines — and the
adjacent executable code contradicts it. This is the cleanest possible
demonstration of the line the scorer now prints on every run, and it is worth
more than another 100% would have been.

**H3 gains a limit.** Cross-model review remains the highest-value phase — it
has caught more real defects today than anything else, at about $0.55 a run.
But the review INSIDE the workflow was not sufficient: it raised the right
blocker and the next phase talked itself out of it. **A review is only as good
as the step that consumes it**, and a revise phase marking its own homework is
not an independent check. The external pass cost $0 extra beyond one codex run
and caught six blockers.

Ten load-bearing claims checked; eight held. Not executing the plan. Posted the
full disposition to #1009.

### Tick 27 — the citation rule bound every claim except the ones doing the work

Fixed the workflow rather than the plan.

**The gap is sharper than "the agent was careless".** `revise.md` ALREADY said
"Reject - explain why the reviewer is wrong, with `file:line` evidence" and
"check anything you are unsure about against the code". Neither was violated.

**A `file:line` cannot evidence a negative.** "That class does not exist",
"there is no such caller", "the submodule is unpopulated" carry no citation by
construction, so a citation rule does not constrain them at all — and absence
is exactly what a rejection rests on. The rule bound every claim except the
ones doing the work.

So both phases now require the COMMAND and its real output when a claim depends
on something not existing, with worked examples, and an explicit instruction to
accept the finding or record an open question when the command cannot be run.
Applied to `revise.md` AND `research.md`, because "dead code, no callers" is
the same shape and the #1009 research phase made exactly that claim.

**This generalises past the workflow, which is why I believe it.** I made this
error four times today and every instance was a negative claim from an
unvalidated query: six workflows "missing" from the Mini, a field "not carried"
by a response, `--tools` "not emitted" anywhere. All three were present. **A
silent empty result reads as evidence of absence and is evidence of nothing.**

**Operational finding: the Mini stores a SNAPSHOT of prompt templates at
install time.** Editing the repo file changes nothing for future runs. I
checked rather than assuming, and it means H6's citation rule was baked in at
install, not read per run. So testing the fix required installing
`sdlc-research-plan-v4` — v3 plus the absence rule, nothing else — and
re-running the IDENTICAL #1009 task (`exec-0bcba7624b96`).

That is the experiment: same task, same model, same four phases, one rule
different. If the revise phase still rejects the agentic-primitives blocker,
it must now paste an `ls` that contradicts itself.

### Tick 28 — my controlled experiment had no codex in it, and finding that out was worth more than the experiment

Installed v4 (v3 + the absence rule, nothing else) and re-ran the identical
#1009 task. Three phases in, cost was **$0.95 against v3's $3.57** at the same
point.

**A 4x drop from adding one paragraph is not plausible**, so I checked the
install instead of writing it up. v4 had **no phase with `provider = codex`** —
the only occurrence of the word was inside a prompt's own text. The
"cross-model review" phase was running as claude. The experiment was measuring
nothing.

Note how close that came to being a result. Last tick I drew a mechanism from a
partial cost number and was wrong; this tick the same instinct was available and
the number was even more striking. **Implausibility is the only thing that saved
it, and implausibility is not a control.**

**Root cause, verified in code:** `_build_phase_defs`
(`commands.py:74-95`) maps `model=p.get("model")` and has no `provider=` line
at all. `phases` is typed `list[dict[str, Any]]` (`commands.py:132`), so the
phase body is never validated — the nested `agent: {provider, model}` block our
own packaged YAML uses is accepted and discarded, and so is any typo. **201, no
warning.**

Filed **#1011**. This is the same accept-then-discard shape as #998, and the
independent plan review found it a third time in `update_phase_prompt`. Three
instances of one bug class in one day, all found by different routes.

**The consequence is bigger than my experiment.** Every codex phase installed
through the API is silently downgraded to claude. Cross-model review is the
phase that has caught the most real defects today — an inert #997 fix, a scorer
that failed toward good, a plan that would have shipped privilege escalation —
at about $0.55 a run. **Install that workflow through the API and you get a
workflow that quietly does not do it.**

H8 is blocked until #1011 is fixed: I cannot install a codex-using workflow
through the API, and hand-editing the stored row to prove a prompt hypothesis
would be measuring a thing users cannot create.

The run is still going. I will read its revise phase as WEAK evidence only —
its cross-model-review input came from claude, not codex, so it is a different
input to the phase under test.

### Tick 28b — the codex review does not cost $0.55, it costs $0.55 plus the work it causes

The invalid v4 run turned out to be a useful control, because it is the same
task with the cross-model review phase silently replaced by claude.

| phase | v3 (real codex) | v4 (provider dropped) |
|---|---|---|
| cross-model-review | `in=68,099`, cache_create **0**, $0.55 | `in=74`, cache_read 669k, $0.28 |
| revise | cache_read **6.43M**, out **71k**, **$4.58** | cache_read 0.38M, out 13.8k, **$0.23** |
| final plan | 57,955 chars | 26,972 chars |
| TOTAL | $8.15 | $1.19 |

**Two things fall out.**

First, a diagnostic: `in=68099` with `cache_create=0` is a **codex signature** —
codex does not use Anthropic prompt caching, so a codex phase shows real input
tokens and no cache. A claude phase shows a tiny `in` and large cache figures.
v4's review has the claude profile. The telemetry corroborated the provider
drop independently of the config, and I would not have needed to read
`_build_phase_defs` at all to know something was wrong.

Second, and this changes how I have been accounting for it all day: I have been
repeating that **cross-model review is the best value in the workflow at about
$0.55 a run**. That is wrong, and it undersells rather than oversells. The
review is cheap; **what it triggers is not.** v3's revise phase read 6.43M
cached tokens and produced 71k output working through real blockers. Without a
real review to answer, the same phase read 0.38M and produced 13.8k.

So the honest figure is **$0.55 for the review plus roughly $4.35 of revision it
causes** — about 60% of the run's total cost, for the phase that found an inert
#997 fix, a scorer failing toward good, and a plan that would have shipped
privilege escalation. Still the best value in the workflow. But "it costs
$0.55" was an accounting error, and the corrected number is the one to defend a
budget with.

n=1 and the two runs differ in more than one way, so the mechanism is stated as
an observation with a plausible cause, not a proven one. What is NOT ambiguous
is the direction: the cheap-looking phase is upstream of the expensive one.

### Tick 29 — one silent drop I noticed, three I could not have

Fixed #1011 rather than working around it, because it blocks H8 and it is a
live dogfooding defect. **PR #1012.**

**Hypothesis going in:** one field was unmapped, so this is a one-line fix.

**Contradicted immediately.** Comparing `PhaseDefinition.model_fields` against
what `_build_phase_defs` actually passes found **four** dropped fields:

| dropped | consequence |
|---|---|
| `provider` | every codex phase installed via the API became claude |
| `allow_delegation` | cross-harness delegation silently off |
| `claude_plugins` (#726) | plugin refs installed nothing |
| `skills` (#772) | **per-phase skill injection installed nothing** |

The last one matters most for this log: `skills` is the feature H2 was testing.

**The part worth keeping:** I found `provider` because a cost number was
implausible. **The other three were not noticeable at all** — no error, no
warning, 201, and a workflow that quietly differs from the one you asked for.
So the main test is structural rather than three more field-specific ones: it
compares the model's fields against what the mapping passes, and adding a field
without mapping it now fails immediately.

That distinction is not academic. Mutation-testing showed `skills` and
`claude_plugins` are caught **only** by the structural test — the field-specific
tests I would have written from the bug report would have missed both. **When
the failure mode is silence, test the mapping, not the symptom.**

Also handled the nested `agent: {provider, model}` spelling, because our OWN
packaged YAML uses it and posting that shape sent the whole block into a key
nothing read.

Preflight exit 0, 643 syn-api + 3254 package tests, untyped-dicts ratchet held
at 94 by typing the new helper `Mapping[str, Any]` rather than raising the
budget. Two pre-push failures caught locally first — an unsorted import and the
ratchet — both because I formatted the source file and not the test, which is
the "lint the commit, not the worktree" trap again.

### Tick 30 — I shipped a guard that certifies coverage it does not provide

Codex reviewed #1012 and requested changes. The finding is about the part I
argued hardest for.

**My structural guard was worthless.** It grepped the function body for `name=`
and asserted every model field appeared between two `def`s. I deleted the real
`skills=` mapping, added a decoy `skills=()` to the DEFAULT-phase constructor a
few lines below, and **all eight tests passed**. Verified before changing
anything.

A guard satisfiable by an unrelated assignment does not measure the mapping. It
is worse than no guard, because it reads as coverage — and I wrote a paragraph
in the PR body explaining why it was the right design.

**The tautology has been climbing levels all day.** Ticks 16, 17, 21 and 24c: a
test asserting something both candidate behaviours satisfy. This one is the
same error one level up — a test asserting something both a correct and a
gutted IMPLEMENTATION satisfy. Same shape, bigger blast radius, and harder to
see because the test looked structural and clever.

Replaced with a round trip: one distinctive value per field, sent in, read back
off the constructed object. **Nothing about how the mapping is written can
satisfy it, only the value arriving.** Confirmed the old bypass now fails.

**Third `bool()` coercion bug today.** `allow_delegation=bool(...)`, and JSON
callers send strings, so `"false"` ENABLED delegation — the caller asking for
the feature off and getting it on. After the artifact primary flag (#1005) and
the api_shape needle (#1010). All three identical in shape; two were found by
review, not by me. I now treat `bool(x)` on anything crossing a boundary as a
defect on sight.

Also learned rather than assumed: a skill ref is `org/repo/skill-name@version`
while a plugin ref names only the repo. My fixture used the plugin spelling and
Pydantic rejected it — validation doing its job on my test.

**Deferred and listed on the PR**, not dropped: read/export still omit three of
the repaired fields (which preserves the original undetectable failure mode
even though storage is fixed), `_build_agent_config_from_phase` drops
`allowed_tools` at execution, multi-name skills bypass expansion, and JSON
create still diverges from YAML validation.

Preflight exit 0, 646 syn-api tests, ratchet held at 94. Two pre-push failures
caught locally again, both the ratchet.

### Tick 31 — I called a regression I introduced "pre-existing, deferred"

Codex pass 2 on #1012. Three findings, all verified before I changed anything.
The first is the one that matters.

**Multi-name skills became the WRONG skill, and that is this PR's regression.**
Passing raw entries to `SkillRef` looked equivalent to the YAML path.
`{"source": ..., "names": ["alpha", "beta"]}` declares two skills; direct
validation produced ONE named after the repo. Verified: a caller asking for
`alpha` and `beta` got a single skill called `b`.

`main` dropped skills entirely. **Absent is recoverable; wrong resolves and
injects the wrong instructions.** I had listed this on the PR under
"pre-existing, deferred" — it is neither, because this PR is what added the raw
mapping. I reached for the deferral category without checking which side of the
change the defect came from, and a reviewer had to tell me it was mine.

**`_as_bool` traded one silent corruption for another.** My tick-30 fix
defaulted a non-bool to False, so `1` and `"true"` DISABLED delegation a caller
asked to enable — still 201, still altered state. Fail-closed is not the same as
correct. It now raises. My docstring also claimed "a string is what JSON sends",
which is false: JSON booleans arrive as real bools.

**And the round-trip test STILL overstated itself.** `execution_type` was
asserted `is not None` against a fixture value of `"sequential"` — the model
DEFAULT — so deleting the mapping satisfied it. Plugins and skills asserted
`len(...) == 1` while the comment beside them claimed identity was checked.

**That is the fifth and sixth tautology today, inside the test I wrote
specifically to escape tautologies, one tick after replacing the previous one
for the same reason.** The pattern is now precise enough to state as a rule:
**an assertion is worthless unless the fixture value could not have arisen
without the code under test.** A default value, a cardinality, a type check —
none of them discriminate.

Mutation-verified against codex's own bypasses: wrong source key and mangled
plugin both fail now. Removing skill expansion killed NOTHING until I added a
verbose-form test, because the shorthand fixture validates identically through
either path. **The fixture has to contain the difference, or the mutation walks
straight through.**

652 syn-api + 3254 package tests, preflight exit 0, ratchet 94.

### Tick 32 — #1012 merged; H8 blocked on a release, verified by probe not by version string

Merged **#1012** (16 checks, `behind main: 0`, two codex passes cleared).
**#1011 closed.** #999 is again the only open PR.

**H8 is still blocked, and I checked rather than assumed how.** The obvious move
was to read a version string off the Mini and reason about it. Instead I probed
the behaviour: installed a workflow declaring `provider: codex` and read it
back.

```
POST /api/v1/workflows -> 201
GET  /api/v1/workflows/probe-provider-check
  provider = None      <- the fix is NOT deployed
```

That is a stronger check than a version comparison, and cheaper. The Mini needs
a release to get the fix, and the release is #999, which is the owner's. So H8
stays blocked for a reason outside my control rather than an unfinished task.
(Probe workflow archived afterwards; archive is the documented soft-delete, not
a leak.)

**Then verified the deferred read/export gap before building on it** — the item
codex reclassified from "incomplete" to "risky to defer":

| field | read model | API response |
|---|---|---|
| `provider` | present | present |
| `allow_delegation` | **MISSING** | **MISSING** |
| `claude_plugins` | **MISSING** | **MISSING** |
| `skills` | **MISSING** | **MISSING** |

So #1012 made `provider` visible end to end, and left three fields **stored
correctly and unreadable**. Filed **#1013**.

**The reason that is worse than an omission is the point of the whole day:** it
preserves the exact failure mode #1011 was about. Storage is right, nothing a
caller can read says so, and export -> import silently loses skills and plugins.
Had `GET` shown these fields, the missing codex provider would have been
obvious immediately instead of taking an implausible cost number to notice.

The issue names a full round-trip test — create, GET, export, reinstall,
compare — rather than per-layer presence checks, because per-layer assertions
pass while the round trip loses data at a boundary between them. That is
precisely how the create-path drop survived.

### Tick 33 — three layers looked right and the data still did not arrive

Implemented **#1013** (the deferred read/export gap). **PR #1014.**

**Hypothesis:** add the three fields to the read model, the projection and the
API response, and they become readable.

**Contradicted at the second step.** I added them to the read model AND the
projection, and the tests still failed. `PhaseDefinitionDetail` can carry a
field while `to_dict()` — the shape actually stored and served — silently drops
it. **Three layers looked right and the data still did not arrive.**

That is the same lesson as tick 29, arriving from the other direction. There I
argued the test must be structural because the failure mode is silence. Here
the failure survived three correct layers and was caught only because the test
crosses boundaries. **Per-layer checks all pass while the value is lost at a
seam BETWEEN them** — which is precisely how the create-path drop survived in
the first place, and it is now the second time in five ticks that a `to_dict`
or a mapping function has been the invisible layer.

Also worth recording: I printed the stored row rather than assuming my
assertion targeted the right shape, and the row had 15 keys and used `id` not
`phase_id`. That is what pointed at `to_dict`. Guessing would have had me
editing the read model again.

Mutation-verified three ways — `to_dict` dropping them (4 tests), the
projection not reading them (3), the legacy default flipping to True (1). The
last matters on its own: a wrong default would report delegation on phases that
never asked for it, which is worse than omitting the field.

Codegen ran, so the OpenAPI spec and the CLI + dashboard types follow.

Four local gate failures caught before push, none of which CI would have told
me faster: an unsorted import, the untyped-dicts ratchet, a duplicated keyword
from a careless string replace, and `_ref_strings` at cyclomatic 12 against a
threshold of 10. Split it in two rather than excepting it.

2399 tests, preflight exit 0, ratchet held at 94.

### Tick 34 — my tests passed while the real read returned defaults

Codex reviewed #1014. Two blockers, both verified before I changed anything.

**The first is the same defect this PR exists to fix, in my own test design.**
`to_dict` wrote the three fields and `from_dict` dropped them, so the value
reached the store and was discarded on the way back out. Every reader goes
through `from_dict`, so I had fixed exactly half the path. A row holding `True`
and two refs reconstructed as `False () ()`.

I wrote a paragraph in the PR body about how these tests "deliberately cross
boundaries". **They cross ONE, and the bug lived at the next.** One commit after
describing why that class is dangerous, I shipped it.

The pattern across today is now unmistakable: **every test I have written that
felt clever measured the side of the boundary I was already looking at.** The
structural grep measured the source text, not the mapping. The round trip
measured the write, not the read. Both times a reviewer supplied the other side.

**Second blocker: my rendering CORRUPTED refs.** `source/name@version` is not a
canonical form — source `https://github.com/foo/bar` with name `bar` rendered
as `.../bar/bar@v1`, which reparses to a different repository, and two refs
differing only in `name_overridden` rendered identically. Worse than the
omission it replaced, because a caller would copy and export the corruption
rather than notice absence. Refs are now carried structurally; joining is not
reversible so I stopped joining.

This is the third time today a "fix" of mine was worse than what it replaced —
after the #997 tree path and the api_shape merge. All three share one shape: **I
produced a summary or a rendering by CHOOSING, where the correct answer was to
preserve.**

Mutation-verified three ways. New tests cross the seam the old ones stopped at.
Codegen re-run. 2403 tests, preflight exit 0, both ratchets held by typing
`to_dict` concretely rather than raising a budget.

Accepted and left visible on the PR: export still emits none of these into
`workflow.yaml`, so export -> reinstall loses them. Its own PR, with the
round-trip test #1013 names.

### Tick 35 — a default asserted only in its default direction proves nothing

Codex pass 2 on #1014 found two mutations my tests survived. Both are the same
hole, one layer further out each time.

**Deleting the endpoint build site passed all nine tests**, because
`PhaseDefinition` supplies False and empty lists from its own defaults and none
of my tests reached `_map_phases` — the mapping a caller's JSON is actually
built from.

**Hard-coding `allow_delegation=True` in `from_dict` also passed**, because
every readback fixture set it True. That gives the rule its sharpest form yet:
**a default asserted only in its default direction proves nothing.** All nine
tests agreed with a literal `True`.

Also fixed something worse than an omission: an entry `from_stored` could not
read became an EMPTY ref, serializing as `{"source_url": null, "name": null,
...}` — indistinguishable from a declared-but-blank reference. `None` used to
be filtered; turning it into an apparently-valid object erased the abnormality
instead of surfacing it. And shorthand is now kept verbatim in `raw` rather
than assigned to `source_url`, because `owner/repo@v1` is not a source URL and
calling it one is the mislabelling that made `_render_ref` dangerous. Codex was
right that my docstring promised to handle shorthand and did not; rather than
make the promise true I removed it.

**H10 registered and refuted: my tests find the bug I am looking for.** Across
ticks 30-35 that has been false four times:

| tick | what my test measured | what it missed |
|---|---|---|
| 30 | source text of the mapping | whether the mapping ran |
| 31 | shorthand skills | the verbose multi-name form |
| 34 | the write side (`to_dict`) | the read side (`from_dict`) |
| 35 | store + read model | the API response mapping |

Every one felt like the careful choice at the time. The generalisation is not
"write better tests" — it is that **I reliably test the side I have just been
staring at, and the defect lives on the other one.** The practical control is
cheap: after fixing layer N, ask what consumes layer N, and test THAT.

Mutation-verified three ways. 2411 tests, preflight exit 0, codegen re-run.

### Tick 36 — the same defect at a third layer, and a mutation that missed its target

**#1014 merged, #1013 closed.** Then took the export gap I had deferred twice.

**Hypothesis:** export drops the same four fields, so this is a small fix.

**Contradicted by measuring.** Comparing `PhaseDefinitionResponse.model_fields`
against what `_yaml_phase_lines` references: **export emitted 6 of 18.** Ten
fields genuinely lost, including `allowed_tools`, `timeout_seconds`, `provider`
and `model`.

So exporting `workflows/sdlc/research-plan` and reinstalling it loses its codex
review phase, every per-phase tool allowlist, and all skills — and reports
success. Filed **#1015**, fixed in **PR #1016**.

**Third layer of one defect.** #1011 dropped fields on create, #1013 on read,
#1015 on the way out. Each was found only after fixing the previous one, and
each time I assumed the fix I had just made was the whole path. The lesson is
not "check the other layers" — I did check, twice, and stopped at the layer I
could see. It is that **a field's journey has more hops than the fix in front
of me suggests, and the only reliable probe is to follow the value rather than
audit the code.**

**Applied H10 deliberately for the first time.** The tests parse the emitted
YAML through a real loader instead of asserting on the string, because the
failure mode is output that is valid YAML meaning the wrong thing — and a text
check is exactly what #1012 shipped and had defeated by a decoy.

**One test corrected its own premise rather than the code.** My negative
control asserted export invents nothing for a bare phase, and it failed on
`timeout_seconds`. Investigating: the RESPONSE model defaults it to 300 while
the DOMAIN field defaults to None, so the API genuinely reports 300 and export
is faithful to what GET returns. Suppressing it would make the export disagree
with the response a caller just read. I changed the test and stated the
ambiguity rather than bending the emitter.

**A mutation killed nothing, and the harness was at fault.** My sed hit a
DIFFERENT `if phase.allowed_tools:` — in the prompt-frontmatter builder, not
the export line. Re-aimed, it fails the named test. Worth recording because
**a mutation that silently misses its target reads exactly like a test that
cannot fail**, and I have spent all day treating the second as the diagnosis.

2422 tests, preflight exit 0.

### Tick 37 — CORRECTION: the instrument already existed and I reached past it

The owner challenged the retrospective in tick 18b/24b, where I wrote that the
fix for my API errors was "building instruments" and that resolutions had
failed. **That framing is substantially wrong**, and the correction is more
useful than what it replaces.

`apps/syn-docs/openapi.json` is **committed in this repo**, 333KB, generated by
`just codegen` — which I ran myself, twice, today. It answers the exact
question I got wrong:

```
WorkflowSummaryResponse has workflow_id?  False
WorkflowSummaryResponse has id?           True
```

One query against that file prevents **#1007 entirely** — the issue I filed and
retracted an hour later — and also prevents the "six workflows are missing from
the Mini" claim, which was the same wrong field name. `syn workflow list`
exists in the CLI, typed against generated types, where `workflow_id` would
have been a **compile error**.

**So `api_shape.py` is substantially a workaround for not using the typed
pipeline this project already built precisely so consumers stop guessing at
shapes.** I reached past `openapi.json` and the CLI for `curl` plus hand-rolled
JSON parsing, and then wrote a tool to solve a problem the project had already
solved.

What survives of the original claim, narrowly:

| question | answered by |
|---|---|
| what fields does this endpoint return | **the committed spec** — 3 of my 4 API errors |
| which key holds this value in THIS response | a live probe |
| is the fix actually deployed on the Mini | a live probe |

The last two are real — a spec describes the contract, not one instance's data,
and the deploy check had to be behavioural. But that is a much narrower
justification than "I needed to build a tool".

**The corrected lesson: the failure was not a missing instrument, it was not
consulting the one the project maintains as its single source of truth.**
"Read the spec, or use the typed client" is both more damning and more
actionable than "build a printer" — and it generalises, because the same
pipeline exists for exactly this reason and I am the second-order case it was
designed to prevent.

Recorded rather than quietly amended, because a retrospective that edits its
own wrong conclusions without saying so is worth less than one that keeps them
visible.

### Tick 38 — release ready and paged; my export fix made packages uninstallable

**Release.** The owner asked whether to cut one today and to be paged when
ready. Checked #999: head IS `main`, so all five of today's merges are in, 50
checks green, 155 commits ahead of `release`. **Paged on ntfy.**

**I nearly reported a false blocker.** `just check-version` said 0.26.0 against
a PR titled 0.27.0, which looked like the bump was missing. It was not — I ran
it in the main repo directory, **89 commits behind main**. The bump landed in
`ddac1d2c`. Seventh stale-tree error today; caught within one command only
because `just bump-version 0.27.0` replied "already 0.27.0 - nothing to do",
contradicting my premise. Removed the worktree and branch I had created on the
strength of it.

Flagged two real deploy notes rather than just "it's green": two projections
rebuild on the Mini (`list_artifacts` v3->v5, `get_workflow_detail` v7->v8) with
an ungated catch-up window, and the Mini currently downgrades codex phases to
claude, which this release fixes.

**#1016: my fix made packages UNINSTALLABLE.** `max_tokens` is deliberately
absent from the authoring schema — `PhaseYamlDefinition` rejects it outright —
so exporting it produced valid YAML the loader refuses. **Strictly worse than
the lossy export it replaced**, which is the fourth time today a fix of mine
was worse than what it replaced.

**And the reason my tests missed it is the same one, one level further out
again.** They parsed the emitted YAML and asserted on the mapping. That proves
it is well-formed; it does NOT prove the loader accepts it. **I tested the
format, not the thing that consumes the format.** Added tests that feed the
output to `PhaseYamlDefinition` — and that single test caught two findings at
once.

Also fixed: plugins were exported with `names:`, which the plugin validator
ignores in favour of the source basename, so `names: [custom]` reinstalled as
`bar`. My test masked it by using an alias equal to the basename — codex spotted
that the fixture could not detect the defect it was written for.

And quoting is now **behavioural**: `_yaml_quote` checked for special
CHARACTERS, so bare `null` erased a field and `123` became an int. It now emits
the bare form, parses it, and quotes unless it survives as the same string.
That is the same shape as the citation scorer's `--rev` fix — stop reasoning
about the rules, run the thing and compare.

Mutation-verified four ways, re-run after a complexity refactor to confirm the
split did not weaken them. 2432 tests, preflight exit 0.

### Tick 39 — v0.27.0 SHIPPED; and my "hotpatch risk" on the Mini was mostly wrong

**Released.** Owner said go. #999 merged (50 checks, `MERGEABLE/CLEAN`, head == main,
155 commits). v0.27.0 tagged, `@syntropic137/cli@0.27.0` on npm, containers in
GHCR as `v0.27, v0.27.0, latest`. Pipeline: **0 non-success.**

**Two corrections to my own reporting, both caught by checking.**

The approval gate: my API call **422'd** on an empty environment id. **The owner
approved it, not me** — the record says `NeuralEmpowerment -> approved`. The run
moved to in_progress right after my failed call, which is exactly the shape of
evidence that invites a false attribution.

The images: my first GHCR query reported **0 images for 0.27.0**, because I
searched the tag `0.27.0` without the `v` prefix. They were published the whole
time. Eighth query-shaped error today.

**Then I told the owner the Mini update was risky, and I was largely wrong.**

I saw `.bak-pre-hotpatch`, `.bak-preswap`, `.bak-pre972` and a live compose
differing by 2 and 47 lines from two backups, and framed it as "hand-patched,
the updater may clobber local fixes". Investigating instead of reporting:

- the **47-line** diff is **version churn**, not hotpatches — it is the
  v0.25.2 -> v0.26.0 generated compose (version header, `logging:`/`deploy:`
  blocks, `SYN_GATEWAY_BIND`, a sigstore mount). The updater wrote those.
- the **2-line** diff is a blank `SYN_WORKSPACE_DOCKER_IMAGE:` in compose, which
  looked alarming because v0.27.0 has `_reject_blank_image` ("an explicitly
  blank image is an error, not a silent fallback", #954).

That second one looked like a real pre-deploy hazard, so I checked the running
container rather than reasoning about compose semantics: **the variable is set**,
from `~/.syntropic137/.env`, to a real digest. The blank line in compose is the
pass-through form. No hazard.

**The one real finding is smaller and sharper than the story I told:** the live
workspace image is pinned to `sha256:9d5bfd8772af` while the release default is
`sha256:29b76b437532`. That is the only thing an update might change, and it is
a one-line question the owner can answer.

**The lesson repeats today's dominant one.** I inferred risk from filenames —
`bak-pre-hotpatch` *sounds* like a hand-patch — and reported it before reading
what the files actually differed by. Backup names are not evidence. Every step
of the real check took one command, and each one shrank the risk.

### Tick 40 — every experiment today ran on an unreviewed edge image

Turned the owner's open question about the Mini's workspace pin into an
evidence-backed recommendation, and found something I had not accounted for.

The two digests are not just different versions, they are **different
channels**:

| | channel | revision | created |
|---|---|---|---|
| live on Mini | **`edge`** | `d37547abb717` | 2026-08-29 01:01 |
| v0.27.0 default | `release` | `276eec0ac231` | 2026-08-29 16:46 |

AGENTS.md is explicit that `:edge` is "explicitly unreviewed and is NOT what
consumers pull". The release default is 15 hours newer and its revision matches
the `PINNED_DIGESTS` gitlink that `preflight` verifies.

**It is the leftover from my own task #41** — "Hot-swap Mini to edge image and
re-run selfhost-selftest-v1" — an experiment that was never reverted.

**The consequence I had not accounted for: every workflow run I measured today
executed on an edge workspace image.** v1, v2, H2, both v3 runs, the v4 run. I
have spent the day controlling for prompt text, phase count and skills while an
uncontrolled variable sat underneath all of it — the agent binaries in the
workspace were from an unreviewed build.

That does not invalidate the results. The comparisons are all *within* that
constant, so H1/H2/H6 still hold relative to each other. But two things are now
untrue that I have been implying:

- "these numbers describe what a user gets" — a user gets the release image
- the H6 effect size is measured on edge binaries, and `claude`/`codex` versions
  differ between channels (the earlier PINNED_DIGESTS work showed 2.1.126 vs
  2.1.250 across two providers)

**Added the caveat to H6 rather than restating the number as if I had known.**
This is the same class as #1004 — an input to every measurement that nothing
recorded — and it is a second argument for that issue: an execution should
record the workspace image digest too, not just the repo commit.

**Recommendation to the owner: move to the release default.** Running unreviewed
agent binaries is not a thing to do by accident, and the pin is accidental.

### Tick 41 — v0.27.0 released; Mini update blocked on SSH, nothing changed

**v0.27.0 is out.** Tagged, npm, GHCR, pipeline 0 non-success.

Attempted the Mini update. **SSH died mid-attempt** — the 1Password agent
refused to sign, the documented intermittency. The failure happened on the FIRST
command (the backup), so **nothing on the Mini was modified**; verified the API
is still healthy on the old version via Tailscale.

Worth noting because it went right: I ordered the operations backup-first, so
the only thing that could fail before any mutation was the backup itself. Had I
led with `setup update`, a mid-command SSH drop would have left a half-updated
stack serving a public URL.

Handed the owner an exact command sequence. The only substantive edit is moving
`SYN_WORKSPACE_DOCKER_IMAGE` off the accidental **edge** pin
(`9d5bfd87`, channel=edge, revision `d37547ab`) onto the release default
(`29b76b43`, channel=release, revision `276eec0a` — matching the
`PINNED_DIGESTS` gitlink).

**Verification does not need SSH.** Once it is up I can confirm everything over
Tailscale:

- `/api/v1/health` returns healthy
- the codex probe: install a phase declaring `provider: codex`, read it back,
  assert `codex` and not `None` — that is the concrete proof #1011/#1012 landed
- `GET /workflows/{id}` now shows `skills` / `claude_plugins` /
  `allow_delegation` — proof #1013/#1014 landed
- the two projections rebuilt (`list_artifacts` v5, `get_workflow_detail` v8)

That list is worth keeping as the shape of a deploy check: **each item is a
behaviour a user can observe, not a version string.** Today I twice reasoned
from a version or a filename and was wrong both times.

### Tick 42 — v0.27.0 deployed and verified; the update silently cut LAN access

**Deployed to the Mini.** Backup first, then update, then re-pin the workspace
image off `edge` onto `release`.

**Two things went wrong, both worth keeping.**

**1. My own command was wrong.** I told the owner to run
`npx syntropic137@latest setup update`. A **typosquat guard** caught it: the
real package is `@syntropic137/setup`. Good that the guard exists; bad that I
handed over an unverified command. I had never run it — I copied the shape from
memory rather than checking, which is the same class as everything else today.

**2. The update silently cut LAN/Tailscale access, and I nearly misread it.**
After updating, every container reported healthy and `curl localhost:8137`
worked on the host, but the API was unreachable from my machine.

My first health check printed `status: healthy` — **from a stale `/tmp` file**,
because the curl had returned `000` and left the previous response in place. I
caught it only because I printed the HTTP code beside the parsed body. That is
the silent-stale-result trap that has produced most of today's wrong claims, and
this time the guard was already in the command.

Root cause, found by hypothesis then check: `.env` still had
`SYN_GATEWAY_BIND=100.112.178.5`, but the **regenerated compose hardcodes
`127.0.0.1:${SYN_GATEWAY_PORT:-8137}:80`** — the v0.27.0 generator dropped the
`${SYN_GATEWAY_BIND:-...}` variable that v0.26.0 emitted. Confirmed with
`docker port`: `127.0.0.1:8137` after the update, `100.112.178.5:8137` after
restoring the variable.

Filed **#1017**. It is the same shape as #1011/#1013/#1015 — a value preserved
at one layer and dropped at the next, with no error — and it is a genuine
onboarding rough edge: healthy containers, a working localhost curl, and a
success message, while every remote consumer breaks.

**Verified the release behaviourally, not by version string:**

| field | before v0.27.0 | now |
|---|---|---|
| `provider` | `None` (silently claude) | **`codex`** |
| `allow_delegation` | absent | `True` |
| `skills` | absent | structured ref (source, name, version, name_overridden) |
| `allowed_tools` | — | `['Read','Grep']` |

So #1005, #1012 and #1014 are confirmed live. **H8 is unblocked** — a codex
phase installed through the API now stays codex.

Loop re-armed at :11 and :41 for the next six hours, with the goal stated as
the owner framed it: dogfood hard enough to build Syntropic inside Syntropic,
closing unknowns by experiment.

### Tick 43 — the carve-out I keep being told not to make, made again

Codex pass 2 on #1016. Four findings, three mine.

**The one that stings: `output_artifact_types` still bypassed quoting.** I had
just quoted `input_artifacts` and `allowed_tools` and left the identical line
next to them alone, because it was pre-existing code I "had not touched". So
`["null"]` emitted `[null]` (which the loader rejects) and `["a,b"]` reinstalled
as two entries. **Fixing the fields I added while leaving an identical one
beside them is exactly the carve-out the owner's standing rule forbids.**

**Per-item quoting was not enough, and the reason is interesting.** `a,b` reads
back as `a,b` on its own, so the per-value check correctly answered "safe" — and
inside `[a,b]` it splits into two. The value was safe; the CONTEXT was not.
Lists are now built by the emitter rather than by joining quoted strings.
Another instance of the day's theme: I tested the value and the defect lived in
what surrounded it.

Also: hand-written double-quoted scalars keep physical newlines, and YAML folds
them, so `"A\nB"` reinstalled as `A B`. Now emitted through the YAML emitter.
And a DERIVED ref name was being exported as an authored one, because the loader
sets `name_overridden=True` whenever a name is present — inventing provenance
the phase never declared.

**Owner asked for local QA before pushing** — CI cycle time and cost add up. So
this push ran the full unit suite, not just preflight: **3149 tests, plus
preflight exit 0.** Worth noting what that showed: preflight alone does NOT
cover unit tests, the dashboard build, or CLI checks, so "preflight green" has
been a weaker claim than I implied on several PRs today. `uv run pytest -m unit`
takes 76 seconds locally against several minutes of CI wall-clock plus billed
runners.

That gap is itself a dogfooding target: **the QA an agent runs before pushing
should be the same set CI runs**, and today it demonstrably was not.

Mutation-verified three ways, all killed.

---

## Tick 44 — merged #1016; built local CI parity; codex refuted its headline claim

**Did:** merged #1016 (both codex passes done, all findings fixed, CI green on
the exact head SHA `e3941d18`, base current). Then built the thing the owner
asked for: one local command that means "CI will pass".

**HYPOTHESIS (H11):** the reason CI catches things my local run does not is that
`just preflight` covers only the static gates, so the fix is to add the missing
jobs to a local target.

**What the evidence said — H11 is true but badly incomplete, and codex proved
it.** The measurement first, since I have been burned by skipping it:

| CI job | had a local equivalent before? |
|---|---|
| `python-qa` | partly — its `check_test_debt.py` step is a HARD gate in CI, and the only local caller passed `--warn-only`, so the local check was structurally incapable of failing |
| `python-unit-tests` | no |
| `dashboard-ui` | partly (no install step) |
| `docs-site` | no |
| `cli-node` | partly (missing `check:api-drift`, `check:untyped-api`) |
| `submodule-check` | no |

So `just qa-ci` + `scripts/check_ci_parity.py` (PR #1019), the gate mapping each
ci.yml job to a local target or to a stated reason it cannot run locally. It ran
green in 3m35s and it immediately caught my own lint errors in 1.5s.

Then codex reviewed it and **falsified the headline claim.** Findings I accept:

1. **`main()` is not tested at all.** The mutation `def main(): return 0` passes
   every one of my seven tests. I mutation-tested the gate by hand at the shell
   and mistook that for the tests covering it — the shell run proves the code
   works today, the tests are what stop it breaking tomorrow. This is H10 again,
   for the fourth tick running: I tested the parsing helpers, which is the side
   of the boundary I was staring at, and not the fail-closed behaviour that is
   the entire product.
2. **The parser is a line regex over YAML.** `jobs: # comment`, a quoted key, an
   uppercase job id, a leading underscore, and a YAML anchor each make it report
   either zero jobs or no jobs block — i.e. **it fails toward "perfect parity"**,
   the exact failure mode I fixed in the citation scorer in tick 22 and then
   rebuilt from scratch here.
3. **It reads ci.yml only.** `docs-lint.yml` triggers on every PR and is not
   mapped. So the claim was false on its face and I never checked the premise.
4. **`dashboard-ci` omits CI's `pnpm link` step** — a transcription miss in the
   very commit whose subject is "make one local command mean CI will pass".
5. **`docs-site-ci` is not equivalent**: Actions sets `CI=true`, under which
   pnpm treats the lockfile as frozen. Locally it can silently update a stale
   lockfile and pass.

**The pattern, stated once.** Three of five findings are the same failure: I
compared target NAMES to job names and called it parity, when parity is a claim
about COMMANDS AND ENVIRONMENT. A gate that compares the wrong two things is
worse than no gate, because it reports coverage.

**Contradicted me:** the commit message says "if this is green, CI is green."
That was not true when I wrote it, and `docs-lint.yml` was one `ls
.github/workflows/` away the whole time — a directory listing I had already run
in this same tick, and read past.

**Also found, filed:** #1018 — local Python is **3.14**, CI pins **3.12**. Every
local test result this week, including yesterday's "3149 tests passed", was
evidence about an interpreter CI never runs. Warned rather than gated: pinning
the owner's interpreter is the owner's call.

**Rough edges hit, both in our own tooling:**
- `sdlc:git-worktree`'s `worktree.sh` fails on macOS: `sed: RE error: parentheses
  not balanced` for any `feat/...` branch (BSD sed, unescaped alternation).
- `codex exec --full-auto` was **removed** in codex-cli 0.147.0. Our
  `delegating-to-codex` skill documents it as the validated invocation, so every
  agent following that skill now gets exit 2. Working form:
  `codex exec -s read-only -c approval_policy='"never"' --json`.

**Next:** fix the five accepted findings on #1019 before a second pass — real
`main()` tests, a YAML parse, every PR-triggered workflow, the link step, and
the frozen install — then re-state the claim as something that is actually true.

### Tick 44b — fixed the five findings, and one of them was wrong

Pushed `a03f7799` and `e05b7514` to #1019. Four of codex's five findings were
real and are fixed as reported. The fifth is worth recording because I checked
it instead of accepting it:

**The review said** omitting CI's `pnpm link` step meant `dashboard-ci` tests a
different dependency graph than CI builds. I added the step, and it wrote a root
`package.json` and modified `pnpm-lock.yaml` and `pnpm-workspace.yaml` — a
verification command mutating tracked files, which is the exact hazard the same
review flagged one section later.

**Checking the premise:** nothing under `apps/syn-dashboard-ui` imports
`@syn137/ui-feedback-react`, its `package.json` does not depend on it, and
`lib/ui-feedback` is not in `pnpm-workspace.yaml`. The link attaches to nothing,
so it cannot change a graph. Omitted, evidence in a comment, CI's dead steps
filed as #1020.

**H3 gets a second limit.** Cross-model review beat me on four counts here,
including one — `main()` untested — that is my own stated discipline turned back
on me. But a reviewer's finding is a hypothesis about the code, not a fact about
it: acting on this one without checking would have shipped a command that
corrupts the developer's checkout. **Two review passes, two `pnpm`-shaped
findings, one of them backwards.** The rule that survives: apply a review finding
only after reproducing the behaviour it claims.

Also added a real assertion for the hazard: `git status --porcelain` is captured
before and after a full `just qa-ci` run and compared. It is byte-identical.
That is the check that caught the mutation, and it now runs every time rather
than living in my memory of this tick.

**Awaiting:** CI on #1019, then codex pass 2, then merge (two-pass cap).

---

## Tick 45 — codex pass 2 on #1019, and a check that could never fail

**HYPOTHESIS:** pass 2 would confirm the four fixes and find little new, since
pass 1 had already been thorough.

**What the evidence said.** Pass 2 confirmed all five dispositions, including
verifying my rejection of the `pnpm link` finding independently (it searched
imports, dynamic imports, CSS, Vite aliases, tsconfig paths, Tailwind and ESLint
config: no consumer). Then it found three more, and testing one of its
*predictions* found something worse than the prediction.

### The finding of the day

Codex predicted `check-submodules` *might* false-pass if `git` itself failed.
I tested the hazard rather than the prediction: deinitialised a nested submodule
so `git submodule status --recursive` printed a line starting with `-`, and ran
the check.

**It exited 0.** The check I had written that morning to catch broken submodules
could not fail at all.

```
set -euo pipefail
if git submodule status --recursive | grep -qE '^[-+U]'; then
```

`grep -q` exits at the first match, the producer dies of SIGPIPE, and `pipefail`
reports the pipeline as **141** rather than 0, so the `if` never fires.
Confirmed directly: same pipeline, `nopipefail=0`, `pipefail=141`.

The mechanism is the inverse of what codex guessed. It expected a failing
producer to mask a clean tree; in fact **the producer fails BECAUSE the check
succeeded**. The more there is to report, the more reliably it is silent.

`check-docs-content` had the same shape from a different cause: `|| true`
swallowed grep's status 2 (unreadable directory) along with its status 1 (no
matches), so a scan that read nothing reported a pass.

### And then the fix created the hazard codex actually predicted

Making the check able to fail made it fail *correctly* on something CI cannot
satisfy: ci.yml checks out with `submodules: true`, which leaves
`lib/event-sourcing-platform/reference/eventsourcing-book` uninitialized, and CI
runs `just preflight`. A recursive assertion would have gone red on every PR.
The earlier run passed only because the check was broken. Now non-recursive,
matching the contract CI actually provides, with the reason in the recipe.

### Also fixed

- **My "cannot run locally" reasons were partly false, and codex proved it.**
  `just deps-audit-py` and `just deps-audit-npm` already run pip-audit and
  osv-scanner; ci.yml DOES run integration tests for PRs based on `release`.
  Replaced one excuse bucket with four distinguishable categories, and the
  runnable-but-excluded ones now name the target that runs them.
- Both mutations codex found surviving: staleness checked against only one
  mapping table, and a scalar `on: pull_request` unrecognised.
- preflight claimed submodules were uncovered one line after checking them.
- The pre-push hook re-ran the em-dash grep preflight now owns.

**Standing hypothesis update.** H10 ("my tests find the bug I am looking for")
stays refuted, but sharpen it: **a passing check is not evidence the check
works.** Four separate gates I wrote today were incapable of failing -
`check_test_debt --warn-only`, the citation scorer's `--rev`, `main() -> 0`, and
this. The only thing that distinguished them from working gates was reproducing
the hazard and watching them go green.

**Method that worked, worth keeping:** every hazard now has a reproduction I ran
(deinit a submodule, move one to another commit, delete a README CI requires,
hide the docs directory), not an argument that it is handled.

**Status:** two codex passes done on #1019, all findings addressed, `just qa-ci`
green in 3m21s, tree byte-identical before and after. Merging on green.

---

## Tick 46 — #1019 merged; two prompt premises were stale; v4 scored

**Merged #1019** (`f671543934b4`) after both codex passes, 0 failing checks.
Architectural Fitness - the job that would have caught the recursive-submodule
mistake - passed on the exact head SHA.

### Two premises in my own tick prompt were false

I have been writing the tick prompts, so these are my errors, not the loop's.

1. **"Build the implement->review->docs->QA half; we have nothing for
   implementation."** `syn workflow list` against the Mini shows
   `implement-from-plan-v1` (Bootstrap / Implement / Open Draft PR),
   `plan-build-pr`, `Code Review` and `PR Review` already installed, and
   `syn execution list` shows implement-from-plan has RUN twice, at $4.06 and
   $8.92. What is missing is not a workflow, it is a *validated* one.
2. **"H8 is now testable - install v4 and re-run."** v4 already ran:
   `exec-0bcba7624b96`, Aug 30 04:50, 4/4 phases, same issue (#1009), **$1.19**
   against v3's **>=$8.15** (v3 has 2 unpriced observations, so its true cost is
   higher still; v4 has 0). I had the answer sitting in the execution list and
   asked for the experiment again.

**HYPOTHESIS (H8):** the v4 absence rule stops the false-premise rejection that
made v3 discard a correct blocker.

### What the evidence said: H8 is still UNTESTED, and something else broke

**H8 cannot be answered by this run.** v4's review phase concluded *"No
blockers"*. There was no blocker to wrongly reject, so the hazard never
occurred. A run that fails safe because the hazard was absent certifies
nothing - the same near-miss trap recorded earlier this week.

**What the run does show, and I did not predict:** citations collapse across
v4's phases.

| phase | v3 `file:line` count | v4 |
|---|---|---|
| investigate | 80 | 25 |
| plan | 33 | 3 |
| review | 54 | 10 |
| **revise (final plan)** | **81** | **0** |

The v4 final plan contains **zero** `file:line` references. Confirmed two ways:
the scorer reports `NO CITATIONS`, and an independent regex over the raw text
finds 0 (v3's finds 81), including inside fenced blocks. It names 25 bare file
paths with no lines.

The discriminating detail is the direction of travel in the last phase: v3's
revise phase *raised* citations 54 -> 81; v4's dropped 10 -> 0. Its own review
had a table of verified `file:line` claims that the revision did not carry
forward.

Where v4 does cite, it cites correctly: its plan-phase 3 citations score
RESOLVES 3/3, EXACT 3/3. Quality per citation held; **density** collapsed.

**Reading it honestly, n=1.** v4 is 1/7 the cost and produced a shorter,
structurally reasonable plan that is far less verifiable. I cannot yet separate
"the absence rule suppressed citing" from "this run happened to go easy" - the
review finding no blockers suggests the whole run was on a lighter path. What is
established is that a v4 plan CAN reach the deliverable with zero verifiable
claims, which is exactly what H6's citation discipline was buying.

**Correction to myself:** I briefly read `total_cost_usd` as a float in one
response and a string in another and nearly filed an API type inconsistency. It
is a string in both; the f-string had hidden the quotes. Checked before claiming.

**Also observed:** `/executions/{id}` returns `total_duration_seconds: 0.0` for
a run that took 10 minutes, and `phase_name: None` for every phase while the CLI
displays names. Not filed yet - needs its own premise check first.

---

## Tick 47 — checked an issue's premise, found it false, then found a live exposure

**HYPOTHESIS:** #1017 is a v0.26 -> v0.27 generator regression that drops
`${SYN_GATEWAY_BIND}`, so the fix is to restore the variable.

**What the evidence said: the premise is false, and I wrote the issue.**

```
$ git show v0.26.0:docker/docker-compose.syntropic137.yaml | grep 8137
315:    - 127.0.0.1:${SYN_GATEWAY_PORT:-8137}:80
$ git show v0.27.0:docker/docker-compose.syntropic137.yaml | grep 8137
317:    - 127.0.0.1:${SYN_GATEWAY_PORT:-8137}:80
$ git log --all -S SYN_GATEWAY_BIND --oneline
(two commits, both my own dogfood-log entries)
```

Both releases hardcode the loopback identically; the variable never existed
here. Codex independently checked all **54** release tags: zero contain it.
There was nothing to revert. The Mini's compose had been hand-edited and
`setup update` regenerated over the edit.

The real defect is the one that forced the hand-edit: **the published stack
offers no supported way to bind the gateway off loopback**, so every
multi-machine operator edits a generated file that every update reverts. That is
worse than a one-release regression, because fixing a generator would not stop
it recurring. Corrected the issue, retitled it, opened #1021 adding the knob
with a loopback default.

### Then the review turned a config change into a security finding

Codex raised the security posture as a hypothesis. **Verifying it** showed:

- `nginx.conf:15` `listen 80;` — `auth_basic off`
- `nginx.conf:37` `listen 8081;` — the only listener with Basic Auth
- the published compose maps the host port to **80**

So `SYN_API_PASSWORD` does not protect the port being published. And my own
field description said *"...so set SYN_API_PASSWORD as well"* — advice that does
nothing, which is worse than no advice.

**It is already live, not hypothetical:**

```
$ curl -o /dev/null -w '%{http_code}' http://<mini-tailscale>:8137/api/v1/health
200                                        # no credentials
$ curl http://<mini-tailscale>:8137/api/v1/workflows
200, 20 workflows                          # no credentials
```

The Mini has served an unauthenticated API and dashboard on its tailnet the
whole time I have been running experiments against it with `-u admin:...`
credentials that were being ignored. Filed **#1022**, paged the owner, and
marked #1021 **draft** rather than merge a footgun. Choosing between "publish
8081 when binding off loopback" and "fail closed on an empty password" changes
behaviour for tunnel users, so it is the owner's call.

### Also confirmed from the same review

- **I edited the wrong operator template.** `infra/.env.example` is for the repo
  workflow; the file actually released and synced to the setup package is
  `docker/selfhost.env.example` (uploaded by `release-containers.yaml:326`),
  still listing only `SYN_GATEWAY_PORT`. A new install would never learn the
  knob exists.
- **My "anything other than 127.0.0.1" is the wrong category** — `::1` is
  loopback and safe.
- **Surviving mutation:** reverting only `docker-compose.selfhost.yaml` while
  the published file stays correct passes all three of my tests, because they
  read only the published artifact. `check-compose` catches it at suite level,
  but the file does not enforce the invariant its own docstring discusses.

### What the tests DID catch

Three mutations killed by the intended test, including reverting the published
compose to the exact #1017 state. Written against `docker compose config`
rather than a regex of the YAML, because docker's interpolation is the consumer
— and a regex test would have passed just as happily on the hand-edit this
replaces. Sentinel `203.0.113.7` (TEST-NET-3) so the value cannot be a default.

**Standing lesson, third tick running:** the reviewer's finding is a hypothesis,
and verifying it is where the value is. Tick 44b, verifying refuted the finding.
Here, verifying escalated it from a code-review nit to a live exposure.

---

## Tick 48 — ran the implementation workflow for real; and a "new bug" that was already filed

**Priority 2, done properly this time.** Tick 46 showed the premise "we have
nothing for implementation" was false. So instead of building a fourth workflow,
I am **validating the one that exists**: launched `implement-from-plan-v1` on
issue #1020 through Syntropic on the Mini (`exec-1717c4da51c8`), not locally.

**HYPOTHESIS (H15):** the existing implement-from-plan workflow can take a
well-specified issue and produce a PR that passes `just qa-ci` with no human
edits.

The task was written to test the discipline, not just the code. It requires the
agent to (a) verify the issue's premise first and STOP if it is false, (b) paste
real command output rather than a summary, and (c) prove `git status` is
byte-identical before and after `just dashboard-ci`. Scoring when it lands:
does a PR open, is the diff in scope, does `qa-ci` pass on its branch, does a
codex pass find blockers. Still running at time of writing (Bootstrap, $0.60).

### Verifying my own two observations from tick 46

I flagged both last tick as "needs its own premise check first". Both checks
were worth doing, and they went opposite ways.

**`phase_name: None` was MY measurement error.** The field is `name`, and it is
populated: `'Investigate the codebase'`. I had called `.get('phase_name')` on a
schema whose field is `name` — the same wrong-field class that produced several
wrong claims earlier this week. Nothing to file.

**`total_duration_seconds: 0.0` is real and systematic.** Six completed
executions sampled, every one 0.0 while their own phases sum to real time:

| execution | total | sum(phases) |
|---|---|---|
| exec-0bcba7624b96 | 0.0 | 619.4 |
| exec-218c408bb916 | 0.0 | 2201.7 |
| exec-167fbe65f189 | 0.0 | 1970.0 |
| exec-efd0d97a0ab7 | 0.0 | 1872.2 |
| exec-e9ad44461d1f | 0.0 | 412.1 |
| exec-090d11b773a2 | 0.0 | 1250.6 |

**And then the premise check stopped me filing it.** It is already **#969**,
with a guard in the projection that exists specifically for it:

```python
#: The ONE field where a zero is known to be wrong rather than authoritative
#: (#969). Measured live: the phase reported 33.004841s while the completion
#: event carried 0.0 ...
_ZERO_IS_SUSPECT = "total_duration_seconds"
```

So the honest report is not "new bug" but **"the fix shipped and the symptom did
not change"**: the guard landed in `ab07cd60` (Aug 29 02:59) and
`git merge-base --is-ancestor ab07cd60 v0.27.0` confirms it is in the release
the Mini runs. A v4 execution recorded on that build, **after** the guard, still
reports 0.0.

Two candidate causes, and I have a live discriminator rather than an argument:
the guard only fires when `existing.get(field)` is already truthy, so if
per-phase accumulation never happens the guard has nothing to protect. The
running `exec-1717c4da51c8` is the first execution I will inspect knowing to
look, on a build that definitely has the guard.

Separately and regardless of cause: the projection's `VERSION` is still **6**
and was not bumped when the guard shipped, so every row built before Aug 29
keeps its 0.0 permanently. A correction that cannot reach existing rows is half
a fix.

**Pattern worth keeping.** Three ticks running, the valuable move was checking a
premise rather than acting on it: tick 46 (two of my own prompt's premises were
stale), tick 47 (#1017's root cause never happened), and now this — a bug report
I was one command away from filing as new.

### Tick 48b — narrowed #969 with a mid-flight reading, then withdrew half of it

Caught the running execution **between phases**, which separates accumulation
from the completion event:

```
status: running | total_duration_seconds: 0.0
  'Bootstrap'   completed  duration=418.065498
  'Implement'   running    duration=0.0
```

A phase completed with 418.07s recorded, the execution total is 0.0, and
`on_workflow_completed` has not fired. So the zero is **not** the completion
event overwriting a good value, which is what the #969 guard defends against.
That is the strongest evidence on the issue so far, and it took one API call at
the right moment rather than another argument.

**Then I over-claimed and had to withdraw it.** I wrote on the issue that the
guard "guards the second half of a path whose first half is failing", implying
accumulation never runs. Reading further refutes my own framing: the phase value
and the running total are set from the **same key on the same event**, one line
apart, and the handler saves. Both branches of the found/not-found split read
the key; neither computes it from timestamps, which was my guess. On a single
event those two values cannot disagree.

Posted the correction rather than leaving a plausible-sounding cause on a bug
someone else may pick up. The empirical observation is reproducible; the causal
story was speculation.

**The pattern this belongs to.** Earlier this week the rule was "a citation is a
claim". This is the same rule applied to a *diagnosis*: a root cause stated
confidently in an issue is load-bearing for whoever fixes it, and mine was
supported only by not having read the next twenty lines. The remaining step
needs instrumentation, not reading, and I said so.

Also recorded on the issue: `VERSION` is still 6, so whatever the fix, historical
rows never pick it up without a bump.

### Tick 48c — H15 scored: the agent did everything right and delivered nothing

`exec-1717c4da51c8` completed. **3/3 phases, 27 minutes, 13.2M tokens, $4.40, no
PR, no branch on origin.**

**H15 REFUTED, and not for the reason I expected.** I was ready to score plan
quality, diff scope and review findings. None of that was the binding
constraint.

**What the agent did, and it was good work.** It verified all three of #1020's
premises independently and pasted real command output for each (`grep` across
`src/`, `package.json`, `vite.config.ts`, `eslint.config.js`, `tsconfig*.json`,
tailwind, `pnpm-workspace.yaml`), made an exactly-scoped 2-file change, and
touched nothing else. The diff is what I would have written.

**What stopped it** is GitHub's own error:

```
! [remote rejected] ... (refusing to allow a GitHub App to create or update
  workflow `.github/workflows/ci.yml` without `workflows` permission)
```

It then checked for a fallback credential, found that `gh` and
`~/.git-credentials` resolve to the same App token, and reported
`IMPLEMENTATION_FAILED` with the reason. Phase 3 wrote `PR_SKIPPED`.

So: **Syntropic cannot change its own CI.** Every self-improvement task touching
`.github/workflows/` is unreachable by a workspace agent, and it fails at the
last step, after the full cost is spent. Filed as **#1024** with the options; the
choice between granting `workflows: write` and routing through a separate
credential is a security posture call, so it is the owner's.

### The finding I did not go looking for

**The execution status is `completed`.**

Three phases completed, execution completed, $4.40 spent, nothing produced. The
only signal is prose inside an artifact nobody reads unless they already suspect
a problem. `syn execution list` shows this beside runs that produced merged PRs.

This is the same failure class as tick 45's gate that could not fail, now in the
observability layer: **an agent that finishes without crashing produces a
completed phase.** There is no supported way to say "I ran to completion and the
outcome is failure", so *the harness broke* and *the task could not be done* are
indistinguishable — and the second is the one a human needs.

That lands directly on the goal. An autonomous loop that dispatches work and
checks status would mark this done and move on. Filed as **#1023**, proposing a
declared per-phase outcome plus an engine-side acceptance check, because a
self-report the engine does not verify repeats the mistake.

### Also, the #969 discriminator completed

`total_duration_seconds: 0.0`, `sum(phases): 1554.4`. A fresh execution, on
v0.27.0, which contains the guard. Consistent with the mid-flight reading.

### What this tick actually bought

An honest answer to priority 2 that no amount of workflow-building would have
produced: the implementation half is not blocked on prompt quality. It is
blocked on a permission bit and on the platform's inability to say "this failed".
Both are now filed with evidence, and both are cheaper to fix than a new workflow.

---

## Tick 49 — landed the blocked agent's work, and widened it to the whole bug class

**HYPOTHESIS:** the agent's #1020 change was correct and only delivery failed, so
landing it myself converts a $4.40 loss into a delivered result.

**Supported, with two things the agent got wrong or left out** — which is a
fairer score for H15 than "it produced nothing":

1. **It dropped a security rationale.** The `ISS-259` comment explaining
   `--ignore-scripts` sat on the step being deleted, and the agent deleted both.
   The remaining install still uses the flag, so the reference moves rather than
   disappears.
2. **It stopped at the two sites the issue named.** Both dashboard Dockerfiles
   also `COPY` ui-feedback, with comments asserting *"resolved via Vite alias and
   tsconfig paths"* and *"ui-feedback is a workspace dep"* — **both false**. Same
   bug class; leaving them would have left false comments claiming a dependency
   that does not exist.

The agent obeyed the scope I gave it, so (2) is my prompt's fault, not its
judgement. Worth noting for the SDLC workflow design: a scope written as a file
list stops the agent from fixing the class, and the owner's standing rule is to
fix the class.

### The verification that mattered

"The build succeeded" would not have been enough — a missing file breaks at
runtime, not build time. The consumer is the served bundle, so I compared that:

| | baseline | without the COPY |
|---|---|---|
| build | ok | ok |
| `assets/index-75LOXfic.css` | present | present |
| `assets/index-Bdu0t_HM.js` | present | present |
| files under `/usr/share/nginx/html` | 8 | identical 8 |

Vite content-hashes its bundles, so **identical hashes prove byte-identical
output**. Had the COPY contributed anything, the hash would differ. That is the
strongest available evidence and it cost one extra `docker run`.

PR #1025. `just qa-ci` green, tree byte-identical before and after.

### Standing-hypothesis nuance

H15 stays refuted — the workflow could not deliver. But the *work product* was
sound, which narrows what needs fixing: **the implementation half of the SDLC
workflow is blocked on delivery capability (#1024) and outcome reporting
(#1023), not on the agent's reasoning.** That is a much cheaper problem than the
one I assumed at the start of the day.

---

## Tick 50 — codex pass on #1025: right conclusion, overstated proof, incomplete class

**HYPOTHESIS:** #1025 is a small, well-evidenced deletion and a codex pass will
confirm it with at most cosmetic notes.

**Half right, and the other half is the interesting part.**

**Confirmed:** the deletion is safe. Codex searched for consumers in the places a
`grep` for the name would miss — bare `@syn137/` specifiers, relative imports
escaping into `lib/`, computed dynamic imports, programmatic Vite aliases,
tsconfig `references`, CSS `@import`, eslint plugin resolution, `pnpm-lock.yaml`
importers and overrides, the nginx config, runtime asset fetches — and found
none.

### My proof was weaker than I wrote

I claimed *"identical hashes are the proof"* of byte-identical served output.
It is not: a truncated content hash covers the Vite module graph, and says
nothing about `index.html`, favicons, or other unhashed public assets. That is
corroboration dressed as proof, in a PR whose whole argument is "verified by
building, not by reading".

Rather than soften the wording I did the comparison:

```
find /usr/share/nginx/html -type f -print0 | sort -z | xargs -0 sha256sum
```

**8 files each, identical byte for byte**, with and without the COPY, for both
the dashboard image and the gateway image. Cost: one extra `docker run` per
image. The claim now matches the evidence.

### I stopped short of the bug class a SECOND time

Tick 49 I widened from the 2 sites the issue named to 4. Codex found **4 more**,
each carrying the same false comment:

| site | claim | reality |
|---|---|---|
| `infra/docker/images/gateway/Dockerfile` | "resolved via Vite alias and tsconfig paths" | no alias — **and this is the image that ships** |
| `docker/docker-compose.dev.yaml` | "ui-feedback is a workspace dep" | not in `pnpm-workspace.yaml`; mount + named volume + declaration |
| `justfile dashboard-install` | — | installed the unused package on every local setup |
| `docs/security-practices.md` | "(submodule, pnpm)" | ordinary files, and the install it documented is gone |

The gateway miss is the one to remember: **it is the production image, and I had
removed the identical three lines from two other Dockerfiles in the same
commit.** Widening once felt like thoroughness and was not.

### The generalisation

Two ticks, two versions of the same error, and they are the same error:
**a claim's confidence outran its evidence** — first "identical hashes prove
bytes", then "I fixed the class" after fixing half of it. The fix in both cases
was mechanical and cheap (run the manifest; grep the whole repo, not the paths I
was already looking at), which is what makes it worth writing down: the cost of
being right here was under two minutes.

Also corrected: `dashboard-ci`'s "same command, same environment, same result"
comment. The command sequence matches ci.yml; the environment does not.
`check_ci_parity.py` never claimed step or environment identity — the contract
was intact, only my wording was not.

`just qa-ci` green, one codex pass, all findings addressed.

---

## Tick 51 — #1025 merged; scoped #1004 and stopped before shipping a fragment

**Merged #1025** (`216eaff3`), closing #1020. All 8 sites of the ui-feedback bug
class gone, both images proven byte-identical, one codex pass, 0 failing checks.

**HYPOTHESIS:** #1004 (record the cloned commit SHA) is a contained change I can
land this tick.

**Not supported — it is three pieces, and two things about it are non-obvious.**

### The trap in the obvious implementation

The natural approach is to resolve the ref on the host at hydration
(`GET /repos/{o}/{r}/commits/{ref}`) and record it. **That records a SHA that
only correlates with what was cloned:** `main` moves, and the clone is what the
agent read.

That is worse than recording nothing, because the value looks authoritative —
which is the exact failure class #1004 exists to prevent. Its own motivating
story is a citation check that gave a confident wrong answer because the tree
was not the tree.

Authoritative is `git rev-parse HEAD` **inside the workspace after the clone**.
A capture path exists: repos are cloned by the generated setup script, and
`run_setup_phase` already returns an `ExecutionResult` to the host, so a marker
line per repo is parseable and unit-testable without a container.

And the acceptance test has to be the hazard: **move the remote's default branch
between the host's resolve and the workspace's clone, and assert the recorded
SHA is the cloned one.** A test against a static repo passes under either
design — the near-miss shape from earlier this week.

### The half that may already exist

`IsolationStartedEvent.image_manifest` and `WorkspaceCreatingEvent.container_image`
are already defined. I could not confirm they are populated on real runs
(`syn events recent` surfaces Lane 2 session telemetry, not these Lane 1 domain
events), but **if they are, the image half is a projection-and-API change rather
than a capture change** — small, and shippable independently.

### Why I stopped

I could have shipped the emit-and-parse piece this tick. It would have been a
parser with no consumer — the same shape as the gate nobody runs and the test
that measures the wrong side of a boundary, which I have now been caught on
three times this week. A fragment that no caller reads is not a third of a
feature; it is a thing that looks done.

So: findings recorded on #1004 with a suggested three-way split, ordered so the
cheap piece (surface the image identity, if already captured) lands first and
makes today's experiment provenance auditable immediately.

**Honest scoring of this tick:** one merge and a design note, not a feature. The
note is worth more than the fragment would have been, but it is not delivery,
and I should not dress it up as such.

---

## Tick 52 — verified last tick's guess about #1004, and it was half wrong

**HYPOTHESIS (from tick 51):** `IsolationStartedEvent.image_manifest` and
`WorkspaceCreatingEvent.container_image` already capture image identity, so that
half of #1004 is a projection-and-API change rather than a capture change.

**Half supported, and the wrong half.** I flagged it as unverified last tick and
said checking it first would avoid building something that already exists. That
was right to flag, and the check paid.

**1. `WorkspaceCreatingEvent.container_image` is dead.** The event is defined,
exported from two `__init__.py` files, and listed in `vsa-manifest.json` — and
**nothing constructs it**. `git grep` finds only the class definition, the
imports, the `__all__` entries and the manifest. So it is not a head start; it is
a field on an event that never fires.

**2. `IsolationStartedEvent.image_manifest` IS populated** —
`workspace_lifecycle.py:195` reads `/opt/agentic/version.json` out of the running
container — but it carries **build provenance, not an image digest**:
`provider_version`, `components`, `build_commit`, `built_at`, and
`manifest_digest`, which is documented as *"Hash of the manifest.yaml used for
the build"*. That is not the OCI digest, and so it does not answer "was this an
`edge` image or a `release` one", which is the question the loop prompt has been
asking all day.

**3. The capture is best-effort and silent.** `_read_image_manifest` returns
`None` on every failure path and "never raises" — correct for a
workspace-creation path that must not fail on telemetry, but it means **a missing
manifest, an old image, and a silently failed read are indistinguishable**. That
is the same shape as the problem #1004 exists to fix: an absent record that reads
like an answer.

### The useful inversion

The image digest turns out to be **easier** than the repo SHA, and for a reason
worth stating: the host both chooses and pulls the image, so there is no race —
it can record the digest it resolved. For the repo it is a bystander; `main`
moves between a host-side resolve and the workspace's clone, which is the trap in
tick 51.

**Host is the authority for the image; the workspace is the authority for the
repo.** That single sentence is what the implementation needs, and neither the
issue nor my first comment had it.

**Honest scoring:** no code shipped this tick. A hypothesis I explicitly recorded
as unverified was checked and corrected, and the correction changes the
implementation plan rather than decorating it. That is the tick's whole output.

---

## Tick 53 — shipped the image half of #1004, and a generalising gate found #969

**HYPOTHESIS:** the image half of #1004 is small enough to ship end to end this
tick, because the host owns the value and there is no race.

**Supported.** PR #1026: `WorkspaceCreatedEvent` carries the digest-pinned
`workspace_image` the command already had, the projection records distinct
images per execution (VERSION 6 -> 7), and the API exposes `workspace_images`.
Empty means NOT RECORDED, never "the default image" — defaulting would invent
provenance for every historical run.

### The part I did not predict

Three defects in this path (#1011, #1013, #1015) were one shape: a value written
correctly and dropped at a constructor that does not pass it, silently taking
its default. **Pyright cannot catch it** — omitting a defaulted field is legal.

So instead of testing only my own field, I wrote a fitness test that walks the
AST of the execution query builders and fails when a name present on BOTH the
read model and the response model is not passed.

**It failed on its first run, on a field I was not looking at:**

```
ExecutionDetailResponse(...) does not pass ['total_duration_seconds']
```

That is **#969**. `ExecutionDetailFull`, the model between the read model and
the response, has no duration field at all — the value is dropped two hops
before the endpoint and the response falls back to 0.0 for every execution ever
run.

**The projection was never the problem.** Which is exactly why reading it twice
found nothing, including my own withdrawn analysis on #969 yesterday. A
generalising gate found in one run what two rounds of careful reading did not.

### The lesson, stated once

I have been writing tests for the bug in front of me. This one was written for
the SHAPE of the last three bugs, and it immediately caught a fourth that nobody
was hunting. **The cost was the same; the yield was a whole class.** That is the
difference between a test and a fitness function, and I have been under-using
the second.

### Also worth recording

- My mutation harness mislabelled two removal mutations as "MISSED TARGET" when
  they had applied — the grep predicate was inverted for deletions. The tests
  failed correctly; the label lied. Verifying the verifier, again.
- `git checkout -b` + a non-unique text anchor put a field on the wrong class
  and duplicated a kwarg. Pyright caught both. Anchors inside a class body need
  a class-scoped edit, not `replace(..., 1)` on the first match.

---

## Tick 54 — codex answered the question I asked, and it blocked my own PR

**HYPOTHESIS:** #1026 records the workspace image end to end.

**REFUTED, on the exact hop I asked codex to check.** I wrote in the review
prompt: *"a field that is always empty is worse than no field, because it reads
as 'this ran on no image'"* — and then shipped exactly that.

**`WorkspaceCreatedEvent` is never persisted.** `_apply()` appends to
`_uncommitted_events`; nothing saves them. Verified independently rather than
taking the review's word:

```
$ grep -n "save\|repository" .../service/workspace_service.py
(no output)
$ git grep -rl "WorkspaceCreated" -- packages/syn-adapters apps | wc -l
0
```

The event is referenced **nowhere** outside `syn-domain`. `workspace_images`
would have been `[]` on every real execution.

**Why I missed it:** I tested the event schema and the read-model round trip —
the two sides I was staring at — and never the hop between them. Identical to
#1011 and #1013, one layer further out. The tests I wrote were good tests of the
wrong boundary.

**A second finding I also accept:** even persisted, the event fires *before*
provisioning succeeds and before the adapter resolves what actually runs. A
permitted local image records a name while an image ID executes; with
verification disabled the value can be a mutable tag; a failed provision still
emits an event called `WorkspaceCreated`. So it records the **requested** image,
not the one that ran. My "the host both chooses and pulls it, so there is no
window" was right about the registry race and wrong about the adapter — a
correlation-not-contract error inside the argument I used to justify the design.

### What survived, and it is the better half

The #969 fix and the fitness gate that found it are independent of all of this
and verified on their own. Split onto a clean branch off main as **#1027**, both
pass-throughs mutation-tested, `qa-ci` green. No rebase, no force push — a new
branch and a new PR.

#1026 is draft with the concrete path recorded: carry the resolved reference
through the isolation adapter into `WorkspaceProvisionedForPhaseEvent`, which the
persisted aggregate emits **after** successful provisioning — fixing persistence
and the timing together. Plus the acceptance test that would have caught this:
drive the provision handler with a fake isolation provider and real
repository/coordinator plumbing and assert the sentinel reaches
`get_execution_endpoint()`. **A unit test on the aggregate or the projection
cannot prove that hop, which is exactly how this shipped.**

### The compounding lesson

Two ticks ago a class-shaped gate caught a bug nobody was hunting. This tick, a
review question I wrote myself caught a bug I had already described in the
prompt. **The pattern is the same: the value came from asking about the shape of
past failures rather than about this change.** What I keep getting wrong is
narrower — I test the objects and not the wire between them.

---

## Tick 55 — the owner caught me not using the system, and using it found three gaps

**The correction, and it lands.** The owner: *"you can run multiple workflows.
The last workflow was run four hours ago, so why aren't you using a self-hosted
system to build Syntropic?"*

Fair. I let ONE blocked run (#1024, `.github/workflows` pushes rejected) stop me
dispatching at all — but that blocker is **path-specific**, and most work does
not touch `.github/`. I had generalised a narrow failure into a total one and
went back to working locally, which is the opposite of the goal.

**Dispatched three in parallel** on the Mini: the #1026 rework via the durable
event (`exec-1205971c9f13`), #1006 premise-check-and-fix (`exec-e8cb453a850d`),
and a session-export cross-check for the SeshMagic question
(`exec-9dcfe2c87357`). Each prompt carries the failure it must not repeat —
notably that a unit test on the aggregate cannot prove the persistence hop,
which is exactly how #1026 shipped broken.

### Three usability gaps, all found by the owner USING it

**1. Phase names render as UUIDs.** The sessions page shows `Phase 20f0e1d7`,
`Phase e4d5d6ad`, `Phase f6702a20`. Those are the real `phase_id`s of
`exec-1717c4da51c8`, and the API already returns names beside them:

```
phase_id= 20f0e1d7-... | name= 'Bootstrap'
phase_id= e4d5d6ad-... | name= 'Implement'
phase_id= f6702a20-... | name= 'Open Draft PR'
```

Pure presentation. With several workflows running at once the column loses all
its value. **#1029.**

**2. The execution does not record what it was asked to do.** Verified: the
detail response has 18 keys and **not one** is task, prompt, input or arguments.
Cost, tokens, phases, artifacts and duration are all preserved; the ask is not.

That is the same class as #1004 — output preserved, the input it should be
judged against discarded — and it blocks the experiment work directly: two runs
cannot be compared if the difference between them was the prompt. **#1030.**

**3. No organization scheme.** 20 workflows on the Mini mix gold-standard
workflows, eval variants (`all Haiku` / `all Sonnet` / `Routed`) and dead
one-off probes, with everything experimental dumped in `custom`. And v3/v4 of
the SDLC workflow are archived, so executions reference workflows that
`syn workflow list` cannot resolve — an experiment you cannot look up. **#1031**,
recorded as a design question rather than a scheme I invent unilaterally.

### Also this tick

Codex pass on #1027 found four things, all accepted. The one worth recording:
**my causal claim on #969 was overstated a second time.** There were TWO causes —
the projection overwrite (already fixed by `ab07cd60`) and the DTO omission. I
wrote "the projection was never the problem"; it was, and it had been fixed.
That is now the third correction I have made on that one issue.

Also: my fitness gate was a name-presence check presented as a data-flow
guarantee — first call only, bare names only, one file, `**kwargs` read as
"passes nothing" — and three of its four exception entries named fields not on
the source model, so they excepted nothing. Hardened, and the three evasions
codex named are mutation-tested and killed.

---

## Tick 56 — #1027 merged, #969 closed; and the review workflows have never run

**Merged #1027** (`99109acf`), closing **#969**. `total_duration_seconds` was
dropped two hops before the response because `ExecutionDetailFull` had no such
field. The projection VERSION is now 7, so historical rows rebuild on deploy —
the earlier zero-guard shipped without a bump, which is why it repaired nothing.

Note the fix is **not live**: the Mini runs v0.27.0, and this is on main.

**Applied my own new skill immediately** and it paid: checked for PRs rather than
statuses. The three parallel runs all report `running` in Implement at ~12.5M
tokens each — real work in flight, no deliverable yet, and nothing to claim.

### The experiment: has the review half ever run?

**HYPOTHESIS:** the SDLC gap is the implementation half; review is covered,
because `PR Review` (3 phases) and `Code Review` (2 phases) are both installed.

**Not supported.** Across all 100 executions on the Mini:

```
$ syn execution list --page-size 100 | grep -icE "PR Review|Code Review"
0
```

**Both review workflows have been installed and never once run.** "Installed"
has been standing in for "works" for as long as they have existed — the same
substitution as the four gates that could not fail. So the SDLC gap is wider
than the loop prompt says: it is not "planning works, implementation missing",
it is "planning validated n=3, implementation runs but cannot deliver, review
never exercised at all".

### The test now running

Dispatched `PR Review` on **#1026** (`exec-8fa79618d42f`) — chosen because it has
**known ground truth**: codex found a blocking defect there that required
tracing the persistence path rather than reading the diff (the event is never
saved, so the field would be empty on every run). The prompt does NOT reveal
that finding, or the test would be void.

Scoring when it lands:
1. does it find the persistence break?
2. does it find that the event fires before the adapter resolves the real image?
3. does it produce false blockers?
4. does it paste real command output, as asked, or summarise?

That is a head-to-head between the in-platform review and an external codex pass
on the same diff, with the answer known in advance.

**Incidental finding, and a good one:** `syn workflow run` refused the dispatch
with `Missing required inputs: --input pr_number=<value> — Pull request number`.
Named both missing inputs and their descriptions. That is the failure mode
#1023 lacks — a refusal that says what to do — and it is worth pointing at when
that issue gets designed.

### Tick 56b — the parallel runs land: one delivered, one timed out, and the answer to the SeshMagic question

**Scored by artifact, not status, per the skill written this tick.**

| run | status | outcome |
|---|---|---|
| `exec-9dcfe2c87357` session export | completed, >=$5.76 | **PR #1033 + a 28KB report**, real |
| `exec-e8cb453a850d` #1006 | **failed**, exit_code=124 | timed out in Implement after 31 min |
| `exec-1205971c9f13` #1026 rework | still running | - |

**The timeout is worth noting for #1023.** This failure was reported CORRECTLY
as `failed` with the exit code. So the completed-when-broken problem is narrower
than I framed it: the platform reports harness failures accurately; what it
cannot represent is an agent that ran to completion and reported failure in
prose. That sharpens #1023 rather than weakening it.

### What the session investigation found

It answers the owner's question, and the answer is **no, not fully**.

The agent traced Command → Event → Projection → Service → HTTP field by field,
and then discovered something better: **it was itself running inside a live
SeshMagic-enabled workspace**, so it verified the join contract against its own
container rather than inferring it:

```
AGENTIC_SESSION_STORE_PROVIDER=seshmagic
AGENTIC_SESSION_STORE_PARTITION=exec-9dcfe2c87357/306ac3b7-...
```

**The headline gap, which I verified myself before filing (#1034):**
`RecordOperationHandler.handle()` is a VSA-compliance wrapper whose entire body
is a comment reading *"When fully integrated, this handler would:"*. The only
real caller writes **one synthetic totals-only operation per session**. So the
schema for per-operation history exists end to end and nothing fills it. Tokens
and cost are real; the operation stream they imply is not.

That matters directly for what is queued: comparing two workflow runs beyond
their totals needs per-operation traces, and #792's parent/child session linking
needs a real operation stream to show nesting against.

Ten more gaps itemised in the report, each with evidence, including a dead
`workspace_path` with no writer anywhere, and tool I/O previews truncated at 500
chars with a silent `{"raw": ...}` fallback so a caller cannot tell truncated
JSON from small JSON.

### The part worth copying

The agent **disclosed a process deviation unprompted**: it had made one `Agent`
tool call violating the phase's no-subagents rule, noticed, stopped, and said so
- noting the findings were independently corroborated by its own reading. It
also correctly resolved a conflict between its embedded task ("open a PR") and
the phase rule ("PR is the next phase"), and explained which took precedence.

That is better reporting discipline than several of my own PRs today.

### Tick 56c — the head-to-head died at five minutes, and that IS the result

**HYPOTHESIS:** the in-platform `PR Review` workflow can find on #1026 what an
external codex pass found.

**Untestable as configured, and the reason is the finding.** `exec-8fa79618d42f`:

```
Gather Context   completed  dur=72.5s
Deep Analysis    failed     exit_code=124
```

Every phase of `PR Review` declares `timeout_seconds: 300`. Correct behaviour,
not a bug — but **five minutes is a fraction of what the review it describes
takes.** Today's cross-model reviews of single PRs ran 5 to 25 minutes each, and
the findings that mattered came from tracing a call path across packages.
`implement-from-plan` budgets its working phase **1800s**, six times as much, and
one run still hit that wall.

So the workflow is structurally unable to produce the output its own phase names
promise — and **nothing discovered that in the months it has been installed,
because it had never been run.** That is H22 with a mechanism attached: not just
"never run", but "never run, and would not have worked".

Filed **#1035**, with the recommendation to measure rather than guess the new
budget, and to question whether 300 should stay the uniform default: it is a
sensible floor for a fetch-and-summarise phase and a trap for an analysis one.

### A second bug from the same evidence

Both timed-out phases report **`duration_seconds: 0.0`**:

```
Implement      failed  dur=0.0    # actually ran ~31 minutes, to its full 1800s
Deep Analysis  failed  dur=0.0    # exit_code=124, i.e. ran to its limit by definition
```

A phase that exits 124 ran for exactly its budget. `0.0` is the least plausible
value available, and it points the reader at provisioning rather than at the
budget — the opposite of the truth. Establishing that the #1006 run had used its
full 1800s meant subtracting timestamps from the execution list by hand.

It also silently distorts `total_duration_seconds`, which sums phase durations —
so any execution with a failed phase under-reports by exactly the working time.
That compounds with #969, fixed hours earlier. Filed **#1036**, with the note to
confirm where the zero enters rather than assume, since the last two duration
bugs in this area were both one hop from where they appeared to be.

### Standing tally for the day's dispatches

| run | outcome |
|---|---|
| implement #1020 | correct work, could not push (#1024) |
| session export | **PR #1033 + 28KB report**, found #1034 |
| #1006 | timed out at 1800s |
| PR Review head-to-head | timed out at 300s (#1035) |
| #1026 rework | still running, 29.8M tokens in Implement |

Two of five hit timeouts. That is a real reliability number, and it is the kind
that only appears once you actually dispatch instead of working locally.

---

## Tick 57 — built the review half, and found the deeper reason it never worked

**Priority 2, the review side.** PR #1037 adds `sdlc-pr-review-v1`.

**HYPOTHESIS:** #1035 is a timeout number to raise.

**The number was the smaller half.** Going to fix it, I could not find the
workflow:

```
$ git grep -rln "Gather Context\|Deep Analysis" -- '*.py' '*.yaml' '*.json'
(no output)
```

**The installed `PR Review` exists only as database state.** A workflow that
gates code review could not itself be reviewed, diffed, or fixed in a pull
request. That is #1031's problem with a concrete casualty attached: the reason
nobody corrected a 300s analysis budget is that there was nothing to correct in
a PR.

The budget itself, stated from measurement rather than taste: cross-model
reviews on this repo this week took **5 to 25 minutes**, and the validated
planner uses **2400s** per phase. 300s is a floor for fetch-and-summarise and a
trap for analysis. New definition: 2400 / 2400 / 900.

### What went into the prompts

Not generic review advice — this week's actual failure mode:

> Attack the hops the diff does NOT touch. The recurring defect here is not a
> wrong line, it is a value written correctly and dropped one hop later, at a
> constructor that omits it or an event that is never persisted. Those hops pass
> every test that looks at either end of them.

That is #1011, #1013, #1015 and #1026 generalised into a review instruction. Plus:
run the commands and paste real output; test the tests by breaking the hop and
checking the test fails; carry forward what could NOT be verified; do not
manufacture findings to look thorough, and do not soften a blocker into a
suggestion.

### What I deliberately did not claim

The PR says it is **not yet run end to end**. Claiming a workflow works before it
has produced a review is precisely what the old one embodied for months, and
writing "installed" where "validated" belongs is the error this whole day keeps
finding. It gets installed and run against #1026 next — the case with known
ground truth.

**Three phases, not one**, for the reason the planner splits research from
planning: a phase that investigates AND judges starts judging early, because
forming a verdict feels like progress.

`just check-workflows` now validates 15 definitions, up from 14. Preflight green.
