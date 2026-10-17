# Implement the task at this checkout

The repository under `/workspace/repos/` is checked out at exactly the commit
the task starts from. The platform pinned it and read HEAD back before you
started.

## The task

$ARGUMENTS

## Rules

- **Work at this checkout and nothing else.** Do not fetch, pull, check out,
  merge, log or show any other ref or commit, and do not look the task up on
  GitHub. This problem has been solved before; reading that solution would
  make this run meaningless, and the run is scored as if you had not.
- **Write nothing back.** Do not commit, push, comment, or open or edit any
  issue or pull request. Your change leaves this workspace only as a patch.
- **Fix the problem, not a test.** Your change is scored by tests you cannot
  see, written against the behaviour the task describes. Write your own tests
  for it as you would for a real change; they are part of your patch.
- You may run tests and any other local command.

## Output

1. Write your change, uncommitted, in the working tree. Then write it out:

   ```
   cd /workspace/repos/<repo>
   git add -A
   git diff --cached --binary > /workspace/artifacts/output/implement.patch
   ```

   The patch must apply with `git apply` at this checkout. An empty or missing
   patch scores as no change.
2. Write `artifacts/output/implement.md`: what you changed and why, and which
   tests you ran with what they printed.

Use `"success": false` only when you could not work on the checkout at all.
