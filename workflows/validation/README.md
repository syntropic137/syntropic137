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
