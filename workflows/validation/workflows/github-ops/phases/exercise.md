---
model: sonnet
description: "Open, comment on, and close an issue to prove GitHub write access"
argument-hint: "[label]"
allowed-tools: Bash
max-tokens: 4096
timeout-seconds: 600
---

Exercise this deployment's GitHub write access against the repository you were
given. Do all four steps, then report.

1. Open an issue titled `syn selfhost validation $ARGUMENTS` with a one-line
   body saying it was opened by an automated validation run and is safe to close.
2. Comment on that issue with the single word `ack`.
3. Close the issue.
4. Report exactly these lines and nothing else:

       ISSUE: <number or FAILED>
       COMMENT: <ok or FAILED>
       CLOSE: <ok or FAILED>
       TOKEN_SCOPE: <what the failure said, or none>

If a step fails, say `FAILED` for that step and put the actual error text in
`TOKEN_SCOPE`. Do not retry a step more than once, and do not work around a
permission failure by choosing a different repository — a refusal here is the
result we want to see, because it tells the operator the App is missing a scope.

Use `gh` for all four steps.
