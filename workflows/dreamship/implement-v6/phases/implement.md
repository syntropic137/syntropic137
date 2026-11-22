---
model: opus
timeout-seconds: 7200
---

# Implement this change, test-first, and open the PR before you finish

$ARGUMENTS

## The one hard constraint on this phase

**Every git operation you need must happen in THIS phase.** Write the code,
commit it, push the branch, and open the pull request here. Later phases run in
fresh containers on fresh clones: a branch you leave uncommitted, or a commit
you leave unpushed, does not exist as far as they are concerned. There is no
later phase that will "do the git part" for you. If you run out of time with
work worth keeping, push what you have and say so in the PR body.

## Three things that DESTROY your work. Read these before you edit anything.

**1. Never touch `.github/workflows/`.** Not to fix a job, not to add one, not
even a comment. The App pushing on your behalf has no `workflows` permission, so
a commit containing any change under that path makes **every** push from this
phase fail — including the quarantine push that exists to rescue your work when
a phase ends badly. A run has already been lost this way: 2511 seconds of
correct work, rejected with *"refusing to allow a GitHub App to create or update
workflow `.github/workflows/test.yml` without `workflows` permission"*, and the
recovery ref could not be written either, so none of it was recoverable. This
repo also does not spend on GitHub Actions, so a CI edit is not wanted here
regardless. If CI genuinely needs changing, say so in your output and leave the
file alone.

**2. PUSH EARLY, and keep pushing.** Create the branch and push it as soon as
you have one commit worth keeping - before the work is finished, before the gates
are green, before the PR body is written. Then push again after each meaningful
step. A phase that does everything and pushes at the end loses ALL of it on a
timeout: that is how `exec-4f269f8a067c` died at 3696 seconds with a correct
commit sitting on a branch no remote had. An unfinished branch on origin is
recoverable by anyone; a perfect branch inside a dead container is not. Open the
PR as a draft early if that helps you push sooner.

**3. Write `artifacts/output/deliverable.md` EARLY, and keep updating it.** The
phase's contract is the artifact, not the code. A phase that does perfect work
and never writes the file is FAILED by the platform and its workspace is torn
down — that is the other half of how the run above was lost. So write a first
version as soon as you know the branch name, and rewrite it as you go. Never
leave it to a final step you might not reach.

## Work test-first

Write the failing test BEFORE the implementation, and run it to watch it fail
for the right reason. A test written after the code tends to assert what the
code happens to do rather than what was asked for, and a test that has never
failed has not been shown to be capable of failing.

Where this repo already has a test for the behaviour you are changing, extend it
rather than adding a parallel one. Where the change is a refactor with no
behaviour change, the test that matters is the one that pins the behaviour you
must not alter: find it, and say which one it is.

Read `AGENTS.md` first. It is the canonical agent context. Pay attention to the
four Event Modeling slice patterns, the content rule (a domain event carries a
reference, never a payload), `assert_test_env!()` as the first line of any mock,
and the no-broken-windows rule.

## Gates, before you push

Run the repo's own gates and make them pass:

    just bootstrap
    APP_ENV=test cargo test --workspace   # or the narrower -p that covers your change
    just vsa                              # hard pre-push gate on contexts/
    just fitness --quick

Do NOT edit `harness/sensors/baseline.json`. A baseline change cannot travel
through `just land` by design, so a branch touching it cannot be landed. If a
fitness floor genuinely blocks you, stop and say so in your output.

Do NOT use `git push --no-verify`. If a hook is broken in a way unrelated to
your change, use `just push-scoped`, and say in the PR body which job you
skipped and why.

If a gate is red and it is NOT your diff, follow AGENTS.md's red-gate triage
ladder: fix it if it takes about 15 minutes, otherwise file a bead with `br
create` and leave an inline comment at the broken site pointing to that bead.
Say which you did.

## Then open the PR

    git checkout -b <type>/<short-slug>
    git add -A && git commit        # conventional commits; cog-verify gates the message
    git push -u origin <branch>
    gh pr create --base main --title "..." --body "..."

The PR body must state plainly: what the change does, what it does NOT do, the
exact commands you ran and their results, and any pre-existing failure you found
with the bead id you filed for it. Do not describe a test as passing unless you
ran it and read the output. If something is unverified, label it unverified.

## Output

Write to `artifacts/output/deliverable.md`: the PR URL and number, the branch
name, the base SHA you branched from, what you changed and why, the commands you
ran with their results, and the single most likely way your change is wrong.

That last item is not optional. Name the weakest point, so the review phase can
start there instead of hunting for it.
