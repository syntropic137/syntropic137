---
model: opus
argument-hint: "[pr-number-or-url]"
allowed-tools: Read,Glob,Grep,Bash
max-tokens: 8192
timeout-seconds: 600
---

Review the pull request specified below.

$ARGUMENTS

Evaluate:
1. Code correctness and potential bugs
2. Test coverage for changed code
3. Security implications
4. Performance considerations
5. Code style and maintainability

Provide specific, actionable feedback with file paths and line numbers.
