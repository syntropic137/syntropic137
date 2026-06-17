# Retro: how `git` ended up in the API container (#726, 2026-05-05)

## What happened

PR1 + PR2 of #726 shipped a registration handler that calls
`subprocess git clone` directly from the FastAPI request handler. The
working git binary was never installed in the `syn-api` container, so
the very first `POST /claude-plugins/global` against a real stack
returned HTTP 500 with no useful body. I (the agent) had earlier told
the user the implementation was "ship-ready" with all gates green.

After the user ran the smoke and the bug surfaced, the user pointed
out a deeper architectural concern: the API is supposed to be a thin
wrapper, and shelling out to `git` from a request handler violates
that contract regardless of whether the binary is available.

## What I claimed vs. what was true

| I claimed | Reality |
|---|---|
| All gates pass, ship-ready | pyright + ruff + pytest green, but the test suite used in-memory adapters; nothing exercised a real container or a real `git` |
| 5 of 5 MUST FIX from review applied | True for the listed items, but the review never examined runtime container dependencies or layer placement |
| Smoke script "for manual verification" | I authored it but never ran it; URL paths assumed nginx prefix; the SLP version `5.0.7` was made up (the repo has no tags) |
| Sub-agent reports trusted | Each sub-agent verified its own slice; nobody verified end-to-end behavior; I aggregated their "clean" reports into "ready" without an independent integration pass |

## Why git landed in the API

Six failures stacked together:

1. **Plan-locked decision.** The plan-local doc explicitly said "subprocess `git clone --depth 1 --branch <version>`" with the rationale "pattern from `setup_phase_secrets.py:309-313`." That citation was misleading: `setup_phase_secrets.py` clones repos *into the agent workspace container*, where git is installed because the workspace base image needs it. I copied the technique without re-asking "which container will run this code at runtime."

2. **No layering challenge during planning.** The plan agent returned a design that placed the fetcher port in `syn-domain/orchestration/ports/`, the adapter in `syn-adapters/git/`, and the handler in `syn-domain/orchestration/slices/register_claude_plugin/`. All structurally correct. But "where is the slice handler invoked from at runtime" was never asked. The answer is: from `apps/syn-api/...`, in a request thread, in the API container.

3. **No runtime-container reasoning.** None of the agents (planner, implementer, reviewer, gap-closer, finalizer) reasoned about which Docker image needs which dependencies. The Dockerfile was never inspected as part of the work.

4. **Test suite blind spot.** The fetcher tests use a local bare git repo via `subprocess.run(["git", "init"...])` from the test harness, which has git installed. They prove the fetcher *works*; they prove nothing about whether the *runtime container* has git. The same blind spot covers the storage adapter (tests use in-memory storage; never touched real MinIO inside the API container).

5. **Code review missed the smell.** The code-reviewer sub-agent found 5 MUST FIX items, all about concurrency, typing, and minor bugs. It did not flag "API container is shelling out to git from a request handler" as an architectural violation, even though CLAUDE.md is explicit:
    > "Thin API wrapper around the domain model"
    > "Long-running processes MUST use Processor To-Do List, no imperative async loops"
   Both of these were ignored by the design.

6. **I treated "tests pass" as proof of correctness.** The CI suite passing tells you the code does what its tests say it does. It does not tell you whether the runtime composition is sound, whether dependencies are installed, whether the architectural seams are right. **Tests-pass != works.** I conflated the two when I told the user "ship-ready."

## What should have happened

Before claiming the work was ship-ready, at least one of these gates should have fired:

1. **A "where does this run?" question during planning.** Any code that does I/O outside the obvious "store this row, return a JSON" loop should have a runtime-container assignment. "Which image runs this slice handler?" should be answered explicitly, alongside "which image needs which dependencies?"

2. **An end-to-end smoke against a real stack BEFORE 'ready' is claimed.** Authoring a smoke script is not the same as running it. The smoke should run as part of the "ready" gate, not as an after-thought handed to the human.

3. **An architectural-seam review.** The code review focused on code quality (types, races, typos). A separate pass should ask: "Does this respect the documented separation of concerns? Does this place an action in the right tier?" CLAUDE.md is explicit; the review should consult it.

4. **Dockerfile diffing.** Whenever code adds a new external dependency (subprocess, library, service call), the corresponding runtime container's Dockerfile needs an update. A simple grep for "subprocess.run/exec" or "asyncio.create_subprocess_exec" in the diff would have flagged the new git dependency.

## What I'm changing

Concrete adjustments to how I work going forward, scoped to this codebase:

1. **No "ship-ready" claim without one successful end-to-end run** against a real or near-real stack. Test pass + types clean is necessary but not sufficient.

2. **Architectural-seam check during planning.** When a slice handler is born, explicitly state: "this runs in <container>" and "the runtime needs <dependencies>." Cross-check against CLAUDE.md's "Thin API wrapper" and "Processor To-Do List" rules.

3. **For new subprocess-shelling code: inspect the runtime image.** Same for new external-service calls, new library imports of native bindings, new long-running operations.

4. **Sub-agent aggregation needs an integration pass.** Each sub-agent's report covers their slice. Before the orchestrator says "ready," it should run one cross-cutting check (smoke + container audit) that no individual agent was scoped to do.

5. **Consult ADR-066 (separation of concerns) before any new I/O.** I'm writing this ADR as part of this same retro work.

## Knock-on effects

- The 5 commits already in `20260502_platform` carry the smell. They are not pushed. The redesign plan (sibling document `redesign-thin-api.md`) describes the rework: move git into the CLI, expose a thin `POST /claude-plugins/trees` endpoint, mirror how `POST /workflows/from-yaml` already does it.
- The bugs the smoke surfaced (HTTP 422 misclassified for nonexistent repos, `added_at` race in the POST response, remove-not-removing) are real and need fixes whether or not we keep the API-side git path.
- The "wrong fix" was to add `git` to the API Dockerfile. I did this on the user's stack to make the smoke proceed, then reverted it locally. The fix is in the architecture, not the image.

## Anchor for future agents

If you are an agent working on this repo and you find yourself adding any of these to the API container:
- a `subprocess.run` or `asyncio.create_subprocess_exec` call
- a network call that is not "talk to my own database/cache/storage"
- an operation that takes more than ~1 second of wall time
- a step that depends on a CLI binary the API doesn't currently use

Stop. Ask: does this belong in the API tier? Consult ADR-066. The answer is almost certainly "no, this belongs in the CLI, in a workspace, or in a processor."
