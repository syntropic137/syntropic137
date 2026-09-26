# Check the premise before anyone builds on it

$ARGUMENTS

You have one job. The task above asserts things about the code - that a function
behaves a certain way, that a field is dropped, that a fix is missing, that a
regression happened. **Find out whether those assertions are true.**

Do not start the change. Do not prepare anything for later phases; every phase
gets its own fresh workspace, so nothing you install here survives this one.

## Why this phase exists

Issues in this repository repeatedly describe defects that do not exist. Three
were caught in a single day: a capability said to be dropped that was carried
correctly, an issue already fixed under a different issue number, and a second
issue already fixed by a merged PR. Each was caught here, before the expensive
phases ran.

Acting on a false premise wastes the whole run, and the PR it produces is worse
than nothing, because it looks like progress and closes an issue that was
already closed or was never real.

**Reporting a false premise is the most valuable outcome this phase has.** It is
a success, not a failure, and it should read like one.

## How to check it

Verify each assertion **against the actual repository**, with commands whose
output you paste. Not by reading the issue and agreeing with it.

Two specific traps, both of which have produced wrong answers here:

- **Read the ref, not the working tree.** A checkout can sit on a stale branch,
  and a `grep` of it describes the past. Use `git show origin/main:<path>` and
  `git grep <pattern> origin/main -- <path>`.
- **The issue number is not the fix.** Work here is routinely merged under a
  different issue number than the one that reported it, so a search for the
  issue number finding nothing proves nothing. Search for the *change* -
  `git log origin/main --oneline -20 -- <the relevant path>` - and read what
  landed.

## What the workspace already gives you

Stated here so you do not spend the phase rediscovering it. These are properties
of the image, not of the task, and they are the same on every run:

- Repositories are pre-cloned under `/workspace/repos/<name>`. **Submodules
  arrive uninitialised**; `git submodule update --init --recursive` if a check
  needs them.
- `/tmp` is mounted `noexec` and `$HOME` is a small tmpfs. Anything that
  materialises scripts or caches needs redirecting:
  `export TMPDIR=/workspace/.tmp XDG_CACHE_HOME=/workspace/.cache UV_CACHE_DIR=/workspace/.cache/uv`
- The image ships `just`, `uv`, `node` and `gh`. It does **not** ship `pnpm`,
  `cargo`, `vsa`, or a Docker CLI - the last deliberately.
- Consequently `just preflight-agent` is the gate that runs here, not
  `just qa-ci`.

**If any of that turns out to be false, that is a finding worth reporting** -
the image changed and these instructions are stale. Report the deviation and
carry on; do not treat it as your main task.

## Write to `artifacts/output/premise.md`

**This phase declares a markdown output artifact, so a run that writes
nothing under `artifacts/output/` FAILS - after the work is done, and the
work is lost with the workspace.** Write the file before you finish, even
if the outcome was a refusal: a refusal is a deliverable and is often the
most valuable one.

Short. Four things:

1. **Does the premise hold?** Confirmed, partly confirmed, or refuted.
2. **The evidence** - the commands you ran and their output, enough that the
   next phase can re-run them rather than trust you.
3. **If it holds:** the specific files and call paths the change will touch.
4. **If it does not hold:** which part is false, and what is true instead. Then
   stop. Do not soften a refutation into "mostly true" - a premise that is
   wrong in the part the change depends on is wrong.
