---
model: sonnet
allowed-tools: Read,Grep,Glob,Write
timeout-seconds: 1800
---

Produce the final refactor plan, revised against the cross-model review.

## The task

$ARGUMENTS

## What you were handed

The coverage verdict, the characterization spec, the extraction plan and the
review are all in your input artifacts. Read all four.

## How to revise

For each review finding, do one of exactly two things:

- **accept it** and change the plan, or
- **reject it** and say why, on the evidence.

Do not silently drop a finding, and do not perform agreement by restating the
finding as though addressing it. If the reviewer was wrong, say so and show the
code that proves it - a reviewer that cannot read the running system will
sometimes be confidently wrong about it.

## The deliverable

One document someone can execute from:

1. **The verdict**, unchanged from the gate unless the review overturned it,
   with the coverage evidence.
2. **The test work that comes first**, sequenced, each one gating a named step.
3. **The extraction steps**, ordered, each leaving a green build, each naming
   its tests and its revert.
4. **What is deliberately not being changed**, and what should be deleted
   rather than extracted.
5. **Open questions** the plan could not settle, stated as questions rather
   than buried as assumptions.

## Do not

- Do not write code or tests.
- Do not add scope the review did not raise and the task did not ask for.
- Do not present an unresolved disagreement as resolved.

Write the final plan to the output directory as markdown.
