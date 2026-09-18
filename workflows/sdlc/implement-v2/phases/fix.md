# Address what verification found

$ARGUMENTS

Read `artifacts/input/verify.md` first. It is the output of an independent
verification pass over the branch you are about to change.

## If verification certified the change, stop

Your first job is to decide whether there is any work here at all.

If `verify.md` reports no blocking defect, **change nothing**. Write
`artifacts/output/fix.md` saying verification passed and that you made no
change, and finish. Do not tidy, do not improve, do not add a test that nobody
asked for. A clean verification is the common case and it must be cheap: this
phase exists to rescue a run that would otherwise be thrown away, not to take a
second bite at work that is already right.

Say plainly in your report which it was, because the phase after you reads it.

## If verification found defects, fix exactly those

The branch already exists and is pushed. An earlier phase did the work, and a
separate model reviewed it and found something specific. That finding is the
whole of your scope.

**Fix the defects named in `verify.md`. Nothing else.** Not adjacent code that
looks wrong, not a refactor you would prefer, not a second feature. The run has
already spent most of its budget getting here; your job is to close the gap, not
to reopen the problem.

The one exception is the standing scope rule: if the SAME defect verification
named appears elsewhere, fix it there too - a fix that closes one instance of a
class and leaves the others open is not a fix. A DIFFERENT problem gets one line
at the end of your report and no edit.

## Take the finding seriously before acting on it

Verification runs on a different model, deliberately, and it is usually right -
but it is not automatically right. Before you change code, confirm the defect is
real by reading the code yourself. Two ways this goes wrong:

- **The finding is correct and you fix the wrong thing.** "The regex excludes
  dots" is a symptom; the fix is to derive the pattern from the grammar it is
  supposed to match, not to add a dot to a hand-written pattern and leave the
  two definitions still independent.
- **The finding is wrong.** If you genuinely believe verification is mistaken,
  say so in your report with the evidence, and do not make the change. An
  unnecessary edit made to satisfy a reviewer is how correct code becomes
  broken. Be specific about why; "I disagree" is not a report.

## The bar for any test you add

Verification has repeatedly rejected work for tests that assert nothing. If your
fix adds or changes a test:

**Show it able to fail.** Mutate the production code so the test goes red,
record the exact mutation and the failure output, then revert the mutation. A
mutation that breaks nothing means the test asserts nothing, and the next
verification pass will catch that and the run will have been wasted twice.

New Python test files need the `unit` marker (`architecture` under
`ci/fitness/`). CI runs `pytest -m unit`; an unmarked module collects zero tests
and goes green over nothing.

## Commit AND push

Push to the same branch the earlier phase used. A commit that never reaches the
remote is quarantined and the phase fails - this has cost real work already.

Run `just preflight` before you push, and commit your auto-fixes: lint the
commit, not the worktree, or local green becomes remote red.

## Write to `artifacts/output/fix.md`

**This phase declares a markdown output artifact, so a run that writes nothing
under `artifacts/output/` FAILS.** Write the file before you finish, including
when the answer is "nothing to do".

1. **What verification found** - one line per defect.
2. **What you changed** for each, with `file:line`, or why you did not.
3. **The mutation** for each test you touched, and the failure it produced.
4. **The commit you pushed**, and the branch.
5. **Anything you disagreed with**, and the evidence.
6. **One line** on any different problem you noticed and did not touch.
