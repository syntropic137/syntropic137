# Prepare the workspace, and check the task's premise

$ARGUMENTS

Two jobs, and the second matters more.

## 1. Find out what the toolchain needs

**Every phase runs in its own fresh workspace, so anything you install here is
gone when this phase ends.** This phase does not prepare anything for the phases
after it; it finds out what they will each have to do, and writes it down.

Determine what the repository needs before its checks can run - submodules,
dependencies, `just` - and record the exact commands, so the later phases can
repeat them rather than rediscover them. If something is missing from the image
itself, say which: that is a finding about the workspace worth reporting.

Do not start the change in this phase.

## 2. Check the task's premise before anyone builds on it

Read the task. It will assert things about the code: that a function behaves a
certain way, that a field is dropped, that a regression happened between two
versions. **Verify each assertion against the actual repository, with commands
whose output you paste.**

Issues in this repository have repeatedly turned out to describe defects that do
not exist: a regression that never happened, a field said to be missing that was
present under another name, a fix said to be absent that had already shipped.
Acting on a false premise wastes the whole run, and the resulting PR is worse
than nothing because it looks like progress.

If a premise is FALSE, say so plainly, state which part and show the evidence,
and do not attempt the change. That is a successful outcome for this phase.

If the premise holds, say which commands established it, and name the hops the
change will have to touch.

## Output

A short report: what the toolchain needed, whether the premise holds, the
evidence, and the specific files and hops the change will involve.
