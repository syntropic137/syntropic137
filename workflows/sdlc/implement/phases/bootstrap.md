# Prepare the workspace, and check the task's premise

$ARGUMENTS

Two jobs, and the second matters more.

## 1. Make the toolchain work

Get the repository to the point where you can run its checks: submodules
initialised, dependencies installed, `just` available. Record what you had to do
and what was already present. If something in the image was missing, say which -
that is a finding about the workspace, not a nuisance.

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
