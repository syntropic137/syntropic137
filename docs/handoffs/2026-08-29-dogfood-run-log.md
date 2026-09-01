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
| H3 | Cross-model review catches what the author cannot | **strongly supported, and it beat me on a direct disagreement** — found #995's traversal; found my #997 fix was INERT; found my scorer failed toward good; and was RIGHT about `--tools` when I publicly said it was wrong (tick 22) |
| H4 | A workflow can do real work on this repo unattended | **supported, with a caveat** — PR #992 opened for $1.09, shipped red CI, and was ultimately closed because the ISSUE was wrong, not the work |
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

---

## H9 - does an experiment phase make a plan trustworthy?

**Hypothesis.** Inserting an experiment phase between a reviewed spec and the
plan produces a plan whose risky unknowns were REDUCED BY MEASUREMENT rather
than reasoned about, and the extra phases cost less than one wrong
implementation.

**Method.** `sdlc-research-experiment-plan-v1` (8 phases: research, codex review,
revise, experiment, revise, plan, codex review, final plan) run on issue #1039
against this repository. `exec-8d5b14716096`. Compared against
`sdlc-research-plan-v3` (4 phases) on cost, and against a peer agent working the
same issue on the host with deployment access.

**Cost.** ~$17.0 for 8 phases, against $2.65 and $3.43 for v3's two arms. Roughly
5x. Phase 1 alone was $3.88, 27 percent of the run. The two codex phases
together were $1.09, under 7 percent.

**Result: NOT SUPPORTED, for a reason that is not about the design.**

All five unknowns came back STILL UNKNOWN. Every one required querying the
running platform, and a workspace cannot reach it: the API sits on a different
docker network from `agent-net`, the `syn` CLI is absent from the workspace
image, and no API URL or token is injected. Filed as #1053.

Meanwhile a peer agent working the same issue ON THE HOST answered all five by
measurement in a fraction of the time and found three classes nobody predicted,
including four claude phases that historically used tools outside their own
declaration. The measurements that decided the issue were available; they were
just not available from inside a phase.

**So the experiment phase is the right idea in the wrong place, for this class
of question.** It works for questions answerable from the repository. It cannot
work for questions about the deployment until #1053 changes.

**What earned its cost anyway.** The two codex phases, at 7 percent of spend:
- rejected the spec's shape and its principal measurement oracle
- corrected `argument_hint`, which the plan and the handoff had both marked for
  deletion, by finding its live dashboard consumer. That correction reached the
  implementing agent before it shipped a deletion
- on the peer's parallel review, found ghost executions and export laundering

The expensive phases produced documents. The cheap phases produced the findings.

**A methodological failure worth recording, mine.** I reported the experiment
phase as having fabricated a verified control. It had not. Its citation was
correct against `main`; I checked a worktree where a peer's commit had already
changed that exact line, and reported the workflow had invented it. Retracted in
`d0a75fe9`. The premise check now added to the experiment phase requires naming
the revision a premise was checked against, because a shared tree moves while a
workflow runs. That rule came from my error, not the workflow's.

**Structural gap found in the shape itself.** The only review phase sees the
first-draft spec. The FINAL unknowns list is written afterwards by `revise-spec`,
so the artifact the experiment phase works from is reviewed by nothing. Recorded
in the workflow header. The structural fix is a second review; the cheaper
mitigation is the premise check.

**What to do with v4.** Do not run it again on a deployment question until #1053
is answered. It remains the right shape for a repository-scoped question, and
the two codex gates are worth their cost on any shape.
