# File the issues and the test prescriptions

$ARGUMENTS

Read `artifacts/input/autopsy.md` first.

Your job is to make sure none of this evaporates. A retrospective whose findings
live only in an artifact gets re-run next month against the same unchanged
behaviour, and the second run costs the same as the first.

## Every finding lands somewhere that can change

For each class and each regression, exactly one of:

- **A GitHub issue** with a reproduction and the prescribed test
- **A comment on an existing issue**, if one already covers it - check first,
  a duplicate splits the evidence across two threads and both look thinner
- **A recorded decision not to act**, with the reason, as a comment on the
  retrospective issue

Nothing may be left as prose in an artifact. That is the whole point of this
phase.

## Check for duplicates before filing

Search open and closed issues for the error string, not for your description of
it. The verbatim quote from the classify phase is the search term that works;
your paraphrase is not.

If an issue exists, add the new evidence to it: how many times it fired in this
window, what it cost, and - most valuable - whether the class is widening.
"Filed as git segfaulting, now also seen in `find` and in secret injection" is
worth more than a new issue that fragments the picture.

## What a good issue contains here

Retrospective issues have a shape that differs from a bug report, because the
value is in the population and the gate analysis:

1. **The cost and the count**, with the window and denominator.
2. **The verbatim error**, so the next occurrence is searchable.
3. **When it fires** in the phase sequence, since that is the cost mechanism.
4. **The reproduction**, concrete enough to run.
5. **The prescribed test** from the autopsy: file, input, assertion, and the
   mutation that makes it fail.
6. **Why the existing gates passed.** This is the part that stops the fix from
   being written with the same blind spot, and it is the part a normal bug
   report never carries.

## Rank, and say what you ranked by

Close by ranking what you filed **by cost**, not by frequency, and say so. An
owner reading this needs to know where to start, and "most expensive first" is a
different order from "most common first" - usually a very different one.

If one class dominates the lost spend, say that plainly in one sentence. A list
of twelve equal-looking issues hides the fact that three of them are the budget.

## Write to `artifacts/output/file.md`

**This phase declares a markdown output artifact, so a run that writes nothing
under `artifacts/output/` FAILS.** Write the file before you finish.

1. **What you filed** - issue numbers and titles, with the cost attributed to
   each.
2. **What you commented on** - existing issue numbers, and what evidence you
   added.
3. **What you deliberately did not file**, and why.
4. **The ranking**, most expensive first.
5. **One sentence** an owner can act on: what to fix first, and what it costs
   not to.

Do not open pull requests and do not change code. This workflow's output is
knowledge and filed work. Dispatch `sdlc-implement-v2` against the issues you
filed - they are written to be dispatchable, which is why the prescribed test
belongs in them.
