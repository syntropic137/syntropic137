# Confirm the fix closed what you found

$ARGUMENTS

## Which round this is

**Round 2 of 3.** This prompt re-verifies after each of up to three fix
rounds. This round's fix report is **`artifacts/input/fix_2/fix.md`** (flat
alias `artifacts/input/fix_2.md`); the verdict that fix round acted on is
`artifacts/input/reverify/reverify.md`. Read the fix report first. It says what the previous phase did about
the defects still open. Write `Round: 2 of 3` as your report's second line.

## Check out the candidate you will certify

**You are in a fresh workspace with a fresh clone of the default branch**, so
nothing you are about to certify is on disk yet. Read the branch, the first-pass
verified SHA and the final pushed SHA from the artifacts, and decide which SHA
is the candidate:

- If `fix.md` says no change was made, the candidate is the SHA the verdict
  that fix round acted on named (the first-pass verified SHA in round 1).
- Otherwise the candidate is the full SHA `fix.md` says it pushed.

Then run:

```
git fetch origin <branch>
git rev-parse origin/<branch>
git checkout --recurse-submodules <candidate-sha>
git rev-parse HEAD
```

The remote head and `HEAD` must both equal the candidate SHA. **If either SHA
is absent from the reports or differs from the candidate, output BLOCKED** and
say which value disagreed: the branch moved after the fix, or a report named a
head that is not there, and either way the thing on origin is not the thing you
would be certifying.

For a repair, read `git diff <first-pass-verified-sha>...<candidate-sha>` and
the resulting code. **Never certify from `fix.md` alone** - it is the claim, not
the evidence.

## If the fix phase changed nothing, say so quickly

In round 2 or 3 this is the case whenever the previous round CERTIFIED: the
fix round made no change, so carry that certification forward on the same SHA.

If `fix.md` reports that the first pass certified the change and no edit was
made, the checkout above has already confirmed it: the remote head is still the
SHA the first pass reviewed. Certify on that, and do not re-run the whole
review. The work was already verified once by a separate model; repeating it
costs a second full pass to learn what you already know.

This is the common case and it must be cheap.

## Otherwise, check the delta, not the world

Your scope is narrow on purpose:

1. **Does the fix actually close each defect the first pass named?** Read the
   code, not the report. A report saying "fixed the regex" is not evidence the
   regex is right.
2. **Did the fix break anything that was previously working?** A targeted edit
   made under time pressure at the end of a run is exactly where a regression
   gets introduced. Check the blast radius of what changed.
3. **Is every test the fix added able to fail?** `fix.md` must name the mutation
   and the failure it produced. If it does not, or if the mutation looks like it
   would not have exercised the assertion, that is a blocking defect - a test
   that asserts nothing is worse than no test, because it will be trusted.

Do NOT re-review the parts of the change the first pass already certified. That
work is done and re-doing it is how a second pass costs as much as the first.

## Be specific about what would make it deliverable

If you find a blocking defect, the next fix round - or, in round 3, whoever
picks up the draft - has only your report to work from. So write it as an
instruction rather than an observation:

- name the file and line
- state what is wrong in one sentence
- state what would close it

"The tests are insufficient" strands the work. "`test_cancel_isolation` builds
one execution, so it cannot fail for the reason #1311 exists; it needs a second
concurrent execution and an assertion that its runtime state is untouched" lets
the next pass finish in one edit.

## Do not move the goalposts

The first pass set the bar. If the fix met it, certify - even if you would
personally have asked for more. Raising the standard on the second pass means no
change can ever pass two reviewers with different tastes, and the run dies for a
reason that is about reviewers rather than about the code.

A genuinely NEW blocking defect introduced by the fix is different, and is in
scope. Say explicitly which it is: "the fix introduced X" or "the first pass
should have caught Y".

## Write to `artifacts/output/reverify.md`

**This phase declares a markdown output artifact, so a run that writes nothing
under `artifacts/output/` FAILS.** Write the file before you finish.

1. **CERTIFIED** or **BLOCKED**, as the first line, in one word.
   Then `Round: N of 3` on the second line. If round 3 is BLOCKED, the third
   line is `Repair bound reached: 3 of 3 rounds used, findings still open.` -
   the run stops here and must not read as though it ran out of anything else.
2. **The branch and the full commit SHA you certified** - or, if BLOCKED, the
   one you checked out and refused - with the `git rev-parse origin/<branch>`
   and `git rev-parse HEAD` output that proves you checked it out. The phase
   after you opens a PR only for that exact SHA, and an abbreviated or absent
   one leaves it nothing to compare against. On a BLOCKED verdict the future
   pass that picks this up needs to know which head your findings describe.
3. **Each blocking defect from `verify.md` and earlier `reverify` reports** -
   every one, not only the ones `fix.md` discusses - and whether it is now closed, with the `file:line` you
   checked.
4. **Any regression** the fix introduced.
5. **The mutation evidence** for tests the fix touched, and whether you believe
   it.
6. If BLOCKED: **what would close it**, file and line and assertion.

A pull request is marked ready if and only if the last round run certifies.

`--recurse-submodules` is required, not optional. Without it `git checkout`
moves the superproject but leaves submodule working directories where they
were, so `git status --porcelain` reports every submodule whose gitlink
differs as modified. The unpushed-work guard treats that as unsaved authored
work and fails the phase AFTER the review is complete but BEFORE it is stored.
That discarded a 21-minute codex review on exec-5a22616362bd (#1499).
