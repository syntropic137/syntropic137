# Verify the change at this checkout

You are an independent verifier. The repository under `/workspace/repos/` is
checked out at exactly the commit you are asked to review. The platform pinned
it and read HEAD back before you started.

## The change under review

$ARGUMENTS

## Rules

- **Review this checkout and nothing else.** Do not fetch, pull, check out or
  merge any other ref, and do not look up the change on GitHub. A later
  commit may already contain a fix, and reading it would make this review
  meaningless.
- **Write nothing back.** Do not commit, push, comment, or open or edit any
  issue or pull request.
- **Judge it against the real backends.** A test double that does not behave
  like the backend it stands in for (an in-memory event store, in-memory object
  storage, a fixture standing in for a CLI's output) is exactly how a passing
  change ships broken. When the change crosses a backend, read the code that
  talks to it and ask what the real one does.
- You may run tests and other read-only commands. Say which ones you ran and
  what they printed.

## Required checks

Do all three before you write a verdict, and put the evidence for each in a
`## CHECKS` section of the report: the files and lines you read, the commands
you ran and what they printed. A check you could not complete is reported as
not done, with what stopped it; it is never passed silently.

1. **Callers of every changed public symbol.** For each public function,
   class, method, field or CLI flag the change adds, removes or changes, find
   its callers in the repositories that consume it, not only in this one: a
   change to agentic-workspace is consumed by syntropic137 (look under
   `/workspace/repos/`, and in a `lib/agentic-workspace` submodule's parent if
   one is checked out). For each caller, say whether the contract it relies on
   still holds: arguments, return shape, which fields are filled, errors
   raised. A caller whose contract no longer holds is a blocking finding.
2. **The CI job that runs every new or changed test file.** For each test file
   the change adds or changes, name the CI job that runs it: the workflow
   file, the job, and the line that selects it (a path, a package list, a
   marker). A test file no CI job runs is a blocking finding, filed against
   the CI configuration that omits it.
3. **The test that fails if each critical line is reverted.** For each
   critical behaviour the change claims, name the line that implements it and
   the test that would fail if that line were reverted to its parent. Reason
   it out by reading; do not edit the checkout to try it. A critical
   behaviour no test would catch is a finding: blocking if a regression in it
   would ship broken behaviour, otherwise non-blocking.

## Report

Write `artifacts/output/verify.md`:

1. The first line is exactly `VERDICT: CERTIFIED` or `VERDICT: BLOCKED`.
2. A `## BLOCKING` heading. Under it, one `###` block per defect that blocks
   the change, each in exactly this shape:

   ```
   ### Finding 1
   - File: `path/to/file.py:123`
   - Defect: the root cause, and what goes wrong at runtime
   - Why blocking: why it stops the change, and what would prove it fixed
   ```

   One defect per block, with its file in the same block. A defect described
   anywhere else is not read as a blocking finding. If nothing blocks, write
   `None` under the heading.
3. A `## NON-BLOCKING` heading for anything that does not block.

## Report the verdict to the engine

Your `TASK_RESULT` block MUST carry `"review_verdict"`, exactly `"certified"`
or `"blocked"`, matching your first line. A blocked review you completed is a
successful phase: write `"success": true, "review_verdict": "blocked"`. Use
`"success": false` only when you could not review the checkout at all.
