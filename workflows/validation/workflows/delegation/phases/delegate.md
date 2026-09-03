---
description: "Codex builds, then delegates a review to claude -p"
argument-hint: "[ignored]"
allowed-tools: Read,Write,Bash
timeout-seconds: 600
---

Do exactly two things.

1. Write `/workspace/palindrome.py` containing `is_palindrome(s: str) -> bool`.
   Keep it short; correctness matters, elegance does not.

2. Delegate a review to Claude Code with a single shell command:

       claude -p --permission-mode bypassPermissions --output-format stream-json \
         --verbose "Review /workspace/palindrome.py for correctness; reply with a one-line verdict"

Then write `artifacts/output/report.md` containing exactly these two lines,
each starting at column 1, and nothing else. The file is what the platform reads
to decide whether this run passed; a report only printed to the terminal counts
as no report at all.

    DELEGATE_RAN: <ok or FAILED>
    VERDICT: <the one-line verdict Claude returned, or none>

The point of this workflow is not the palindrome. It is that a codex-led phase
can hand work to a different harness and that BOTH legs appear in the
execution's cost breakdown afterwards. A run where the delegation silently does
not happen still produces a working palindrome, so report `FAILED` honestly if
the command did not run.
