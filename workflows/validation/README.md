# Self-host validation workflows

These test whether a **deployment** works, not whether a change is correct. They
exist because v0.26.0 shipped a configuration that made every workflow fail at
phase 1 with zero tokens, and no test in the repo could have caught it: the unit
suite does not run a container, and the dev stack is not `read_only`.

Each workflow asserts one capability an operator would otherwise discover by
having it fail during real work.

| workflow | asserts |
|---|---|
| `skills-injection` | a vendored skill AND an external pinned skill both reach the agent's context |
| `delegation` | a codex leader can hand work to `claude -p`, and BOTH legs get priced |
| `github-ops` | the GitHub App token can open an issue, comment, and close it |

## Running

    syn workflow install workflows/validation
    syn workflow run selfhost-skills-injection-v1 -i task="..."

Each is deliberately small. They are a smoke test, not a benchmark: the question
is "does this capability exist on this deployment", not "how well does it work".

## Why the assertions are in the prompts

A phase that merely *uses* a capability can succeed for the wrong reason - an
agent that cannot see an injected skill will often complete the task anyway from
general knowledge, and the run goes green while the mechanism is broken. So each
phase is asked to REPORT a specific observable fact (a filename, a sentinel
string, an issue number) that is only available if the capability actually
worked.

## Why the assertions are ALSO in the workflow (#1085)

Asking for the fact is not the same as checking it. Until #1085 nothing read
those reports: execution status answered "did the agent finish", so a run whose
report said `CLOSE: FAILED` finished green and the operator had to open the
transcript to find out that the capability was broken. A validation workflow
that cannot fail is not a validation workflow.

Each phase therefore declares what its output must contain:

```yaml
    asserts:
      - '^ISSUE: [0-9]+$'
      - '^CLOSE: ok$'
```

Every entry is a Python regular expression, searched in MULTILINE mode against
the content of each file the phase wrote under `artifacts/output/`. If any entry
matches nothing, the phase fails and the execution fails with it. An empty or
absent `asserts` keeps the old behaviour exactly: judged on the agent's exit
code alone.

Two consequences worth knowing before writing one:

- **The report must be a FILE.** Assertions are matched against collected
  artifacts, not against what the agent said, so a phase that only prints its
  report has nothing to assert against and fails. Each prompt here writes
  `artifacts/output/report.md`.
- **The workflow declares the verdict, not the agent.** The alternative was a
  `TASK_RESULT: PASS/FAIL` line from the agent itself, which is cheaper and
  asks the thing under test to grade itself. The sentinel in
  `skills-injection` is the reason this matters: it is evidence precisely
  because the agent cannot produce it without the mechanism working.
