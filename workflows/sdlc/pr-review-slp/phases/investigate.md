---
argument-hint: "<PR number or a description of the change to review>"
---

# Review this change across every leverage point at once

$ARGUMENTS

A single reviewer picks two or three concerns and misses the rest. You are not
going to review this alone.

## First: resolve and record the refs

This workspace is a fresh clone checked out on the DEFAULT branch, not on the
PR. `git diff origin/main...HEAD` would compare main against itself and show
you nothing, and an empty diff read as "a small change" is the worst possible
start - for you and for all eight subagents you are about to send into it.

So name the refs explicitly:

```bash
git fetch origin
git rev-parse origin/main            # the BASE SHA - record it
git rev-parse origin/<pr-branch>     # the HEAD SHA - record it
git diff origin/main...origin/<pr-branch>
```

If the diff is empty, stop and say so - that means the refs are wrong, not that
the PR is trivial. **Record both SHAs in your output, labelled base and head.**
The next phase gets its own fresh clone and checks out the head SHA you record;
without it that phase reviews the default branch, and a review of two different
commits is not a review.

## What you have

Eight leverage-point skills are installed in this workspace. Each one is a
review discipline with its own checklist, its own failure modes, and its own
idea of what "wrong" looks like:

`architecture` · `software-complexity` · `testing` · `security` · `types` ·
`error-handling` · `dry` · `dependencies`

Read one of them if you want to see the shape. They are not advice documents;
they are review procedures.

## What to do with them

Fan out. Dispatch one subagent per leverage point, in parallel, and give each
one exactly one job: review this change through that single lens and report
what it found.

Each subagent must be told, in its own prompt, to invoke its leverage-point
skill by name. Do not paraphrase the skill into the prompt yourself - the skill
body is the review procedure, and a summary of it is not the same instrument.

Send them all in one message so they run concurrently. Eight sequential
subagents is the thing you are here to avoid.

## What each subagent owes you

A finding is only useful if someone downstream can act on it, so require of
each: the exact `file:line`, what breaks, and the concrete input or state that
makes it break. A concern without a failure path is an opinion, and this phase
produces evidence, not opinions.

Tell them plainly that finding nothing is a real result. A lens that reports
"no issues under this discipline" is more useful than one that manufactures a
finding to look productive, and you should say so in the prompt you give them.

## Then do the part they cannot

You have all eight reports; none of them has the others. So:

**Deduplicate.** The same defect will surface under several lenses wearing
different names. Merge those into one finding and note which lenses saw it -
a defect that three disciplines independently flag is a stronger signal than
one that only `dry` noticed, and that ranking is information the individual
reports cannot contain.

**Reconcile contradictions.** Two lenses will sometimes disagree, and the
disagreement is usually the interesting part. Do not average them or quietly
drop one. Say what each claimed and which the code supports.

**Rank by consequence,** not by which lens raised it and not by how easy it is
to fix.

**Separate what was verified from what was asserted.** A subagent that read the
code and traced the path is on different footing from one that pattern-matched
a smell, and the phase after this one needs to know which is which.

## Write to `artifacts/output/investigate.md`

- **The base and head SHAs**, labelled, exactly as `git rev-parse` printed
  them. The `verify` phase checks out the head SHA and gates on it; it has no
  other source for it.
- **What the change claims to do**, and where that claim comes from.
- **Findings, ranked**, each with `file:line`, the failure path, and the lenses
  that raised it.
- **Contradictions between lenses**, and what the code actually supports.
- **What each lens reported as clean** - this is not filler. The phase after
  this one is trying to falsify a claim, and knowing which disciplines already
  looked and found nothing tells it where not to spend its budget.
- **What could not be determined**, and what would settle it.

## Citing code

Every `file:line` reference MUST be the path from the repository root, exactly
as `git ls-files` prints it, for example
`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/workflow_definition.py:401`.
A reviewer who cannot locate your evidence will discard it.

## One honesty requirement

Record how many subagents you dispatched and how many returned. If a subagent
failed or came back empty, say so in the output rather than silently reviewing
with seven lenses and reporting as if you had eight. A missing lens that nobody
notices is exactly how a review certifies an unexamined area as clean.
