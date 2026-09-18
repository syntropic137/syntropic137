# Confirm the fix closed what you found

$ARGUMENTS

Read `artifacts/input/fix.md` first. It says what the previous phase did about
the defects the first verification pass found.

This is the **second and final** verification pass. There is no third. What you
report here decides whether the run delivers a pull request or throws away
everything it has paid for, so be decisive: say whether the branch is
deliverable, and if it is not, say exactly why in terms the next run can act on.

## If the fix phase changed nothing, say so quickly

If `fix.md` reports that the first pass certified the change and no edit was
made, confirm that is true - check the branch head is the one the first pass
reviewed - and certify. Do not re-run the whole review. The work was already
verified once by a separate model; repeating it costs a second full pass to
learn what you already know.

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

If you find a blocking defect, the run ends without a PR and the branch is left
for a future pass. That future pass will have only your report to work from, so
write it as an instruction rather than an observation:

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
2. **Each defect from the first pass**, and whether it is now closed, with the
   `file:line` you checked.
3. **Any regression** the fix introduced.
4. **The mutation evidence** for tests the fix touched, and whether you believe
   it.
5. If BLOCKED: **what would close it**, file and line and assertion.

The phase after you opens a pull request if and only if you certify.
