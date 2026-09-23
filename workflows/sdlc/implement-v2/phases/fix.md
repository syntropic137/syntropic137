# Address what verification found

$ARGUMENTS

Read `artifacts/input/verify/verify.md` first. It is the output of an
independent verification pass over the branch you are about to change. If that
file is absent, fall back to the temporary compatibility alias
`artifacts/input/verify.md`.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file.

If neither exists, write `artifacts/output/fix.md` explaining that the
verification input is missing, and stop without changing or pushing anything.
You have no findings to act on, and a fix phase that guesses at what
verification might have said edits a certified branch at nobody's request.

## If verification certified the change, stop

Your first job is to decide whether there is any work here at all.

If `verify.md` reports no blocking defect, **change nothing**. Write
`artifacts/output/fix.md` saying verification passed, that you made no change,
and naming the branch and the full verified SHA that `verify.md` reported - the
phase after you checks that exact SHA out, and your report is where it looks for
it. Then finish. Do not tidy, do not improve, do not add a test that nobody
asked for. A clean verification is the common case and it must be cheap: this
phase exists to rescue a run that would otherwise be thrown away, not to take a
second bite at work that is already right.

Say plainly in your report which it was, because the phase after you reads it.

## Check out exactly what verification reviewed

**You are in a fresh workspace with a fresh clone of the default branch.** The
branch you are about to repair is not here yet. Read the branch name and the
full verified SHA from `verify.md`, then run:

```
git fetch origin <branch>
git rev-parse origin/<branch>
git checkout -B <branch> <verified-sha>
git rev-parse HEAD
```

Both `rev-parse` results must equal the verified SHA, and paste both into your
report. If the remote branch has moved, or either value is missing or different,
**do not edit and do not push**: report the mismatch in `fix.md` and stop.
Something pushed over the branch after it was reviewed, and repairing a tree
nobody verified produces a diff no pass in this run has ever seen.

After committing, push normally. **Never force-push** - the remote head is the
verified head, so a fast-forward is the only push that can be correct here, and
one that is not fast-forward means the check above should have stopped you.

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

Before pushing, run:

```
mkdir -p /workspace/.tmp /workspace/.cache
export TMPDIR=/workspace/.tmp XDG_CACHE_HOME=/workspace/.cache UV_CACHE_DIR=/workspace/.cache/uv
just preflight-agent
uv run pytest -m unit -q
```

`preflight-agent`, not `preflight`: this workspace ships `just`, `uv` and
`node` and nothing else, so the full target's `vsa`, Cargo, pnpm and Docker
gates cannot run here at all (#1109). The `TMPDIR` exports are not decoration
either - `/tmp` is mounted `noexec` and `just` materialises every shebang
recipe into a temp directory, so without them the gate dies on its first recipe
before it reaches your change (#1100).

Record the final output of both commands in `fix.md`, and commit any tracked
auto-fixes before pushing: lint the commit, not the worktree, or local green
becomes remote red.

## Write to `artifacts/output/fix.md`

**This phase declares a markdown output artifact, so a run that writes nothing
under `artifacts/output/` FAILS.** Write the file before you finish, including
when the answer is "nothing to do".

1. **What verification found** - one line per defect.
2. **What you changed** for each, with `file:line`, or why you did not.
3. **The mutation** for each test you touched, and the failure it produced.
4. **The identity the next phase checks out**: the branch, the full first-pass
   verified SHA, and the full SHA you pushed - or, if you changed nothing, say
   so explicitly and give the verified SHA as the unchanged head. Full SHAs,
   not abbreviations: the next phase compares them against `git rev-parse`.
5. **Anything you disagreed with**, and the evidence.
6. **One line** on any different problem you noticed and did not touch.
