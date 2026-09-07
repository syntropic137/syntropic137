# Make the mechanical change and open the PR

$ARGUMENTS

You are the ONLY phase in this workflow. Nobody checks your work after you.
There is no verify phase, no cross-model review, no second reader before the
PR exists. Everything below follows from that.

This workflow exists for changes whose correctness a reviewer confirms by
LOOKING at the diff. It is not a faster version of `sdlc-implement-v1`; it is a
different tool, and the first thing you do is decide whether the task in front
of you is actually one of its cases.

## First: is this in scope?

Read the task, then look at what it would actually take in the repository -
not at how the task describes itself. Tasks arrive labelled trivial and turn
out not to be.

**The test is not size. It is: is there anything to prove?** A 200-line
mechanical rename is in scope, because a reader confirms it by reading it. A
three-line change to error handling is not, because a reader has to reason
about what now happens when it throws.

### In scope

- Dependency version pins and lockfile bumps.
- Typos, in code comments, docs, log strings or user-facing copy.
- Dead or moved links, and broken doc cross-references.
- Config values: a timeout, a port default, a feature flag's default, an
  environment variable's documented value.
- Renaming a constant, variable, function or file, with all references updated,
  where the rename changes no behaviour.
- Deleting dead code the compiler, the type checker or an exhaustive grep
  proves unreachable.
- Formatting and lint fixes a tool produced and you did not hand-edit.

### Out of scope

Stop if the change touches any of these, however small the diff:

- Behaviour, of anything. If the program does something different afterwards,
  it is out of scope.
- Control flow: a new branch, an inverted condition, a changed loop bound, an
  early return.
- Error handling: what is caught, what is raised, what is swallowed, what is
  retried, what a failure path now does.
- Event schemas, event payload fields, aggregates, or anything that changes
  what a stored event means or how it replays.
- Projections and read models, including a field that merely looks additive -
  it changes what a rebuild produces.
- Security, auth, tokens, secrets, permissions, sandbox settings or
  `allowed_tools`.
- Tests that assert behaviour. Renaming a test is in scope; changing what it
  asserts is not.
- Concurrency, ordering, timing or idempotency.
- Anything where you would have to work out WHETHER it is correct rather than
  SEE that it is.

If you are between the two lists, it is out of scope. The list is a floor, not
an exhaustive enumeration, and the tie goes to the slower workflow.

## If it is out of scope, BAIL OUT. Change nothing.

This is an instruction, not a suggestion, and it overrides the task's own
framing of itself.

Stop. Do not make the change, do not make a partial change, do not make "the
safe half" of the change. Do not open a PR. Write an artifact that says
plainly:

> This task is out of scope for `sdlc-quickfix-v1` and needs
> `sdlc-implement-v1`.

then name which out-of-scope category it fell into and what you saw in the
repository that put it there. Be specific enough that a human can agree or
disagree with you without redoing your investigation.

**Why this matters more than finishing.** A mechanical path that quietly
attempts a judgement call is worse than having no fast path at all. The change
still gets made, but now it carries a trivial-change label, it skipped the
cross-model gate, and the reviewer's attention has been actively misdirected
away from the one diff that needed it. Every guard the four-phase workflow
spends money on exists because unreviewed behaviour changes are expensive to
find later.

Bailing out is a SUCCESSFUL outcome for this phase. It costs one sonnet run and
it routes the work correctly. Attempting it and getting away with it is the
failure mode, precisely because nothing downstream will catch it.

The same applies mid-task. If you start on something that looked like a config
value and find it is load-bearing, stop there and bail out - revert what you
have written and report. Sunk effort is not a reason to continue.

## Making the change

Branch from current `origin/main`:

```
git fetch origin
git checkout -b <branch> origin/main
```

Never rebase and never force push - this repository merges `main` into feature
branches, in that direction, always.

Make the whole change. If the task names two files and the same typo is in
four, fix four and say so; a fix that leaves identical instances behind is a
carve-out, not a fix. Widening the change is fine and staying inside the scope
lists still applies to the widened part - if instances three and four turn out
to be load-bearing, that is a bail-out, not a judgement call you get to make.

Do not touch anything under `.github/`. Pushes carrying workflow changes are
rejected by the platform's credential, deliberately, so a change there cannot
be delivered from here. If the task requires one, stop and say so.

## Run the gates

```
mkdir -p /workspace/.tmp /workspace/.cache
export TMPDIR=/workspace/.tmp XDG_CACHE_HOME=/workspace/.cache UV_CACHE_DIR=/workspace/.cache/uv
just preflight-agent
uv run pytest -m unit -q
```

Paste the final lines of each into your artifact and into the PR. Real output,
not a summary of it, and never a number you did not read from a command.

**The `TMPDIR=` prefix is a workaround, not decoration.** This workspace mounts
`/tmp` `noexec`, and `just` materialises every shebang recipe into a temp
directory before running it, so with the default `TMPDIR` the gate dies on its
first recipe with `Permission denied (os error 13)` before reaching your
change. `$HOME` is a 128 MB tmpfs and uv, ruff and node all cache under it, so
a run that redirects only `TMPDIR` dies later with `No space left on device`.
Both are tracked (#1100, #1120, #1133). Do not "fix" either by editing the
justfile or running the recipes by hand - that hides the condition the prefix
compensates for.

**`preflight-agent`, not `qa-ci`.** This workspace ships `just`, `uv` and
`node` and nothing else, so seven gates in `just preflight` cannot run here at
all: `vsa-validate` (no `vsa`), `fitness` (no `cargo`), `codegen-check` (no
`pnpm`), `check-submodules`, `check-compose-overlays`,
`check-default-workspace-image` and `check-pinned-image-channels`. CI runs
those seven. Passing here does not promise a green CI; name them in the PR as
not run.

**If a gate fails, do not open a PR.** Report what failed, paste the output,
and stop. This is the same refusal discipline the four-phase workflow applies,
and it matters more here: there is no verify phase behind you to catch what you
waved through. A red gate on a change that was supposed to be mechanical is
also evidence the change was not mechanical - consider whether the honest
report is a bail-out.

Run `git status --porcelain` before and after the gates. Gates in this
repository have mutated tracked files; if the tree changed, say so.

## Commit, push, open the PR

Commit with a message that says what changed and why. Push the branch to
origin. Then open the PR against `main` with `gh pr create`. Do not merge.

### The PR body MUST declare its own provenance

**This is non-negotiable and there is no version of this phase that skips it.**

The PR body must contain, prominently and near the top, a paragraph to this
effect - in your own words, but making every one of these points:

> **No independent verification.** This PR was produced by
> `sdlc-quickfix-v1`, a single-phase workflow for mechanical changes. There
> was no separate verify phase and no cross-model review. The only checks
> behind it are the gates quoted below, run by the same agent that wrote the
> change. It was routed here on the judgement that its correctness is visible
> in the diff - if you disagree with that judgement, that is the thing to
> review first.

Then the ordinary contents: what changed, why, the gate output, which gates
could not run in this workspace, and anything you deliberately did not do.

**Why this is mandatory.** Every other PR in this repository arrives having
passed a cross-model gate, and reviewers have calibrated on that. A PR that
looks like the others but had none of it borrows trust it did not earn, and the
reviewer's error is invisible to them - they cannot tell from the diff which
workflow produced it. The declaration is what keeps the fast path honest. A
quickfix PR without it is a defect in this workflow, not a formatting nit.

## Output

Write your artifact to `artifacts/output/`. It must contain:

- The scope decision, and what it rested on. If you bailed out, that is the
  whole artifact and you are done.
- What you changed and why, and the full diff.
- The branch name, the full commit SHA you pushed, and the PR URL.
- The real final lines of `just preflight-agent` and `uv run pytest -m unit -q`.
- What you deliberately did not do.

If no PR was opened, say why in one sentence at the top.
