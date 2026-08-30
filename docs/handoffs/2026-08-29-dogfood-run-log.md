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
| H8 | A rule requiring the COMMAND behind an absence claim stops false-premise rejections | **still blocked, tick 32** — #1011 fixed and merged (#1012), but a behavioural probe shows the Mini does NOT have the fix. Needs a release, which is the owner's call |
| H6 | A prompt line requiring root-relative citations moves EXACT without costing RESOLVES | **strongly supported, n=3, corrected instrument** — #990: 55/55, #1004: 37/37, #1009: 51/51. RESOLVES and EXACT both 100% in all three. EXACT 75% → 100% for +85% cost |
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
