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

## Report

Write `artifacts/output/verify.md`:

1. The first line is exactly `VERDICT: CERTIFIED` or `VERDICT: BLOCKED`.
2. Under a `BLOCKING` heading, each defect that blocks the change: the file and
   line, the root cause, what goes wrong at runtime, and what would prove it
   fixed.
3. Under a separate heading, anything that does not block.

## Report the verdict to the engine

Your `TASK_RESULT` block MUST carry `"review_verdict"`, exactly `"certified"`
or `"blocked"`, matching your first line. A blocked review you completed is a
successful phase: write `"success": true, "review_verdict": "blocked"`. Use
`"success": false` only when you could not review the checkout at all.
