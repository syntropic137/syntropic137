# Fork-to-Resume Rename and Orchestration Ubiquitous Language: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `resume` the single name for continuing work that did not finish, free the word `fork` to mean copying any prior execution, and write the orchestration context's ubiquitous language down so the distinction survives.

**Architecture:** Three renames in dependency order - free the `resume` name from its current pause/resume holder, take it for the execution-continuation concept, then rename the surfaces. A payload-shape discriminator protects the one real hazard: the string `ExecutionResumed` changes meaning, so an event written under the old meaning must never be silently read as the new one. The definitions land first and act as this plan's own spec.

**Tech Stack:** Python 3.14, Pydantic v2, FastAPI, event-sourcing-platform (ESP) SDK, Node/TypeScript CLI, Fumadocs (Next.js), pytest, ruff, pyright, vsa, APSS fitness.

**Spec:** This document's "Decisions" section below. The owner specified the vocabulary directly in conversation on 2026-09-27; no separate spec doc exists, so the decisions are recorded here and the ubiquitous language file created in Task 1 becomes the durable canonical source.

## Decisions (the spec)

1. **Full rename, not surface-only.** The owner chose option (B): rename the domain, the events, the API and the CLI. Rationale, in their words: naming alignment is a maintainability property, and `fork` must be reserved as a canonical word in the bounded context's ubiquitous language.
2. **`resume`** applies to an execution that did not finish: `failed`, `interrupted`, or `cancelled` (the last still requiring an explicit override).
3. **`fork`** applies to any execution that has completed at least one phase - including a `completed` one - and copies it from a chosen completed phase. **Not built in this plan.** Task 9 files the issue.
4. **The incumbent must move.** `ExecutionResumed` currently means un-pausing a paused execution. It becomes `ExecutionUnpaused`, freeing `resume`.
5. **A ubiquitous language doc per bounded context is expected and missing.** `docs/architecture/es-glossary.md` covers ESP *patterns*; the ESP submodule has its own Axon-aligned vocabulary. Neither defines this system's domain terms. Task 1 creates the orchestration one; Task 2 explains the convention in AGENTS.md.

## Global Constraints

- **No `max_tokens`-style dead fields.** Do not add configuration that nothing reads.
- **Cross a slice boundary through an injected collaborator, never an import.** `vsa-validate` enforces it and this feature has tripped it four times.
- **A domain event may import `aggregate_execution.value_objects` and not an aggregate's other modules**, and may not import `collections.abc`. Guards belong in `value_objects`.
- **No string-literal `getattr` in `apps/syn-api`** (lint rule; two production bugs behind it).
- **New test files carry `pytest.mark.unit`** or CI collects nothing and the gate passes having run none of them.
- **Do not raise `check_untyped_dicts` budgets.** `syn-domain` is at 440/440; type the state instead.
- **No em dashes in any file.** Use plain hyphens.
- **Every TODO/FIXME cites a GitHub issue.**
- **`fork` in the process sense must survive untouched**: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/handlers/skill_install.py:24-25` documents `GRPC_ENABLE_FORK_SUPPORT` and the grpc-fork-under-uvloop crash. A rename that touches those comments is a defect.
- **Gates to run and report before finishing any task:** `just vsa-validate`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest -q -m unit`, `uv run pytest ci/fitness -q`, `just fitness-check`.

## Review Focus

Five conditions the spec implies that no task's happy path exercises. Each has a test assigned to the task that owns the code.

1. **A legacy `ExecutionResumed` event written under the OLD meaning is replayed by new code.** Measured on 2026-09-27: zero exist in production (0 of 26,917 events; `ExecutionPaused`/`ExecutionResumed` absent entirely). But the window between this merge and the deploy is not closed, and a single pause/resume in that window writes one. Expected behavior: the old payload is recognised by shape and never interpreted as a resume-from-failure. Test owned by Task 4.
2. **An `ExecutionForked` event written by the pre-rename build is replayed.** Measured: the fork route is not deployed (404 on the Mini), so none exist in production - but one exists in any developer's local on-demand env. Expected: it either upcasts to `ExecutionResumed` or fails loudly; it must not be silently dropped, which would make a parent look unforked and admit a second resume. Test owned by Task 4.
3. **A caller hits the old `POST /executions/{id}/fork` route after the rename.** Expected: a clear 404 or a documented redirect, not a 500. Test owned by Task 5.
4. **A user runs `syn control resume` after the verb becomes `unpause`.** Expected: the alias works or the error names the new verb; silence is a support ticket. Test owned by Task 6.
5. **The words drift apart again.** Expected: a fitness test fails if `Fork`/`fork` identifiers reappear in the orchestration context outside the allow-listed process-fork comments, so the reserved word stays reserved until the fork feature claims it. Test owned by Task 8.

---

### Task 1: The orchestration bounded context's ubiquitous language

The definitions are the spec for every later task, so they land first and get reviewed on their own.

**Files:**
- Create: `docs/architecture/orchestration-ubiquitous-language.md`
- Modify: `docs/architecture/README.md` (link it)
- Modify: `docs/architecture/es-glossary.md` (a pointer line: ESP patterns here, domain terms there)
- Test: `ci/fitness/code_quality/test_ubiquitous_language_exists.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the canonical spelling of every term later tasks rename to - `Resume`, `Fork`, `Inherited Phase`, `Resume Phase`, `Pin`, `Admission`, `Unpause`. Later tasks must match these exactly.

- [ ] **Step 1: Write the failing test**

```python
"""The orchestration context must carry its own ubiquitous language.

A bounded context whose vocabulary is not written down drifts: `fork` and
`resume` were used interchangeably for one operation until 2026-09-27, and the
word `fork` was spent on it. This test is why that cannot silently recur.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_DOC = Path("docs/architecture/orchestration-ubiquitous-language.md")

#: Every term the orchestration context commits to. A term added to the domain
#: without a definition here is the drift this test exists to catch.
_REQUIRED_TERMS = (
    "## Execution",
    "## Phase",
    "## Workflow",
    "## Resume",
    "## Fork",
    "## Inherited Phase",
    "## Resume Phase",
    "## Pin",
    "## Admission",
)


def test_the_doc_exists() -> None:
    assert _DOC.is_file(), f"{_DOC} is the canonical vocabulary and is missing"


@pytest.mark.parametrize("term", _REQUIRED_TERMS)
def test_every_committed_term_is_defined(term: str) -> None:
    assert term in _DOC.read_text(), f"{term} is used in the domain and undefined in {_DOC}"


def test_fork_is_reserved_and_says_so() -> None:
    """`fork` names a capability that does not exist yet.

    Until it does, the definition must say so, or a reader will assume the
    behaviour is available and the word will be re-spent on resume.
    """
    body = _DOC.read_text()
    fork_section = body[body.index("## Fork") :]
    assert "not implemented" in fork_section.lower() or "not yet" in fork_section.lower(), (
        "the Fork definition must state that the capability is reserved, not shipped"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest ci/fitness/code_quality/test_ubiquitous_language_exists.py -v`
Expected: FAIL, `docs/architecture/orchestration-ubiquitous-language.md is the canonical vocabulary and is missing`

- [ ] **Step 3: Write the document**

Create `docs/architecture/orchestration-ubiquitous-language.md`:

```markdown
# Ubiquitous Language: Orchestration

## Purpose

The vocabulary of the `orchestration` bounded context. These words have exactly
these meanings in code, in the API, in the CLI and in conversation. Where a term
here disagrees with any other document, this one is canonical.

This is the DOMAIN vocabulary. For event-sourcing patterns - Event, Aggregate,
Projection, Processor - see `es-glossary.md`. For the event store's own
vocabulary see `lib/event-sourcing-platform/docs-site/docs/event-store/concepts/ubiquitous-language.md`.
A term belongs here when it names something this system's users talk about, and
there when it names a mechanism the platform provides.

Every bounded context gets one of these. See AGENTS.md, "Ubiquitous Language".

---

## Execution

One run of one Workflow, identified by an `exec-` id, recorded as an event
stream. An Execution is never rewritten: its history is the record of what
happened, including how it ended.

Terminal statuses are `completed`, `failed`, `cancelled` and `interrupted`.
`running` and `paused` are live; `not_started` has produced nothing.

## Phase

One step of a Workflow inside an Execution, with its own agent, model, prompt
and timeout. Phases run in a total order given by `order`, which
`WorkflowDefinition.from_yaml` guarantees is unique per Workflow.

A Phase is `completed` only when the Execution recorded it so. A Phase that
started and did not complete has no partial credit: there is no mid-phase
resume.

## Workflow

The definition a run is made from - its Phases and their configuration.
Mutable: installing a Workflow replaces it. An Execution therefore PINS what it
needs rather than reading the Workflow later.

## Resume

Continuing an Execution that DID NOT FINISH, by starting a new Execution that
inherits the Phases already completed and restarts at the first one that did
not.

Applies to `failed` and `interrupted` on request, and to `cancelled` only with
an explicit override - a cancel was a decision, and resuming past it needs a
fresh one.

The new Execution has its own id. The original stays exactly as it was,
including its terminal status, and records that it was resumed. One resume per
Execution.

Resume is NOT un-pausing. See Unpause.

## Fork

Copying any Execution that has completed at least one Phase - INCLUDING a
`completed` one - into a new Execution that starts from a CHOSEN completed
Phase rather than from the first unfinished one.

Where Resume derives its starting point, a Fork is given one. Where Resume
carries the original configuration unchanged, a Fork is the operation that
exists in order to vary something - a model, a prompt - against the same
baseline.

**Not implemented.** The word is reserved so that the capability can be built
without renaming anything. Tracked in the Fork issue; until it ships, an
operation that continues unfinished work is a Resume and is called one.

## Inherited Phase

A Phase a resumed Execution does not re-run, because the Execution it came from
completed it. Carries the artifact ids that Phase produced, and the id of the
Execution that actually produced them - which may be an ancestor further up a
chain, not the immediate predecessor.

## Resume Phase

The Phase a resumed Execution starts at: the first Phase, in order, that the
original did not complete. Restarted from its beginning.

A Resume Phase that had already STARTED in the original may have pushed or
published something, and re-running it repeats that; resuming such an Execution
requires the operator to acknowledge it.

## Pin

A fact an Execution records about itself at start so that it can be reproduced
without consulting anything mutable: the full runnable configuration of every
Phase, and the commit each repository was at.

A Pin is why a resumed Execution runs what the original ran even if the
Workflow has been edited since.

## Admission

The decision that an operation may proceed, recorded before any work begins.
Resuming an Execution is admitted or refused against the original's recorded
state; the new Execution is then created and started by a background processor.

An admitted resume is not a started one. The two are separate facts and a
successful API response reports the first.

## Unpause

Returning a `paused` Execution to `running`. The SAME Execution continues - no
new id, nothing inherited.

Called Unpause, not Resume, because Resume means the other thing. Before
2026-09-27 this operation was called resume, which is the collision this
vocabulary exists to prevent.

## Words we do not use

- **Branch.** Reserved; no meaning assigned. If a chat-style "branch from here"
  operation is ever wanted, this is where it gets defined.
- **Retry.** Means a Phase attempt within one Execution
  (`PhaseRetryScheduled`), never a new Execution.
- **Fork, in the process sense.** `GRPC_ENABLE_FORK_SUPPORT` and
  `os.fork` are unrelated to this vocabulary. Renames must not touch them.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest ci/fitness/code_quality/test_ubiquitous_language_exists.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Link it from both neighbours**

In `docs/architecture/README.md`, add to the document list:

```markdown
- [Ubiquitous Language: Orchestration](orchestration-ubiquitous-language.md) - the domain vocabulary of the orchestration bounded context. Canonical for Execution, Phase, Resume, Fork.
```

In `docs/architecture/es-glossary.md`, directly under `## Purpose`, add:

```markdown
This glossary covers event-sourcing PATTERNS. For the domain vocabulary of a
bounded context - what an Execution or a Resume is - see that context's
ubiquitous language, e.g. `orchestration-ubiquitous-language.md`.
```

- [ ] **Step 6: Run the docs gate**

Run: `just check-docs-content`
Expected: typography check passes (no em dashes)

- [ ] **Step 7: Commit**

```bash
git add docs/architecture/orchestration-ubiquitous-language.md \
        docs/architecture/README.md docs/architecture/es-glossary.md \
        ci/fitness/code_quality/test_ubiquitous_language_exists.py
git commit -m "docs(architecture): write the orchestration context's ubiquitous language

The vocabulary was never written down, and it cost the word `fork`: one
operation was called both fork and resume until the two meanings were
separated. This is the canonical source, with a test that fails when a
committed term loses its definition."
```

---

### Task 2: Explain the convention in AGENTS.md

**Files:**
- Modify: `AGENTS.md` (new subsection after `### Bounded Contexts & Aggregates (ADR-020)`, which ends at line 249)
- Test: `ci/fitness/code_quality/test_ubiquitous_language_exists.py` (extend)

**Interfaces:**
- Consumes: the file path created in Task 1.
- Produces: nothing code depends on.

- [ ] **Step 1: Write the failing test**

Append to `ci/fitness/code_quality/test_ubiquitous_language_exists.py`:

```python
def test_agents_md_explains_the_convention() -> None:
    """A convention no one is told about is not a convention.

    AGENTS.md is the primary context every agent and contributor reads; the
    ubiquitous language is worthless if nothing points at it from there.
    """
    agents = Path("AGENTS.md").read_text()
    assert "Ubiquitous Language" in agents, "AGENTS.md must explain the convention"
    assert "orchestration-ubiquitous-language.md" in agents, (
        "AGENTS.md must link the orchestration vocabulary"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest ci/fitness/code_quality/test_ubiquitous_language_exists.py::test_agents_md_explains_the_convention -v`
Expected: FAIL, `AGENTS.md must explain the convention`

- [ ] **Step 3: Add the section to AGENTS.md**

Insert after the Bounded Contexts table, before `### TODO/FIXME Standard`:

```markdown
### Ubiquitous Language

Every bounded context has a written vocabulary, and it is canonical. This is
inherited from the event-sourcing platform this system is built on: a bounded
context is defined by the language spoken inside it, so that language is an
artifact, not folklore.

| Scope | Document | Covers |
|---|---|---|
| ESP patterns | `docs/architecture/es-glossary.md` | Event, Aggregate, Projection, Processor, Bounded Context |
| Event store | `lib/event-sourcing-platform/docs-site/docs/event-store/concepts/ubiquitous-language.md` | the store's own Axon-aligned terms |
| `orchestration` | `docs/architecture/orchestration-ubiquitous-language.md` | Execution, Phase, Workflow, Resume, Fork, Pin, Admission |

**Rules:**

- A domain term used in code, the API or the CLI MUST be defined in its
  context's vocabulary. `ci/fitness/code_quality/test_ubiquitous_language_exists.py`
  fails when a committed term loses its definition.
- One word, one meaning, per context. `resume` means continuing an Execution
  that did not finish; un-pausing is `unpause`. The two were the same word
  until 2026-09-27 and the ambiguity reached the CLI.
- A word RESERVED for unbuilt work is still defined, and its definition says it
  is unbuilt. `Fork` is reserved this way.
- A context without a vocabulary file needs one written before its terms
  spread. Four of the five contexts still lack theirs.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest ci/fitness/code_quality/test_ubiquitous_language_exists.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md ci/fitness/code_quality/test_ubiquitous_language_exists.py
git commit -m "docs(agents): explain the ubiquitous language convention

Inherited from the ESP: a bounded context is defined by the language spoken
inside it, so the language is an artifact. Names the three scopes, the rules,
and that four contexts still lack a vocabulary file."
```

---

### Task 3: Free the name - the incumbent becomes Unpause

Runs before Task 4 so that `ExecutionResumed` is unoccupied when the resume concept takes it.

**Files:**
- Rename: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/ExecutionResumedEvent.py` to `ExecutionUnpausedEvent.py`
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/__init__.py`
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/WorkflowExecutionAggregate.py` (the `resume_execution` handler and its `@event_sourcing_handler("ExecutionResumed")`)
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/commands.py` (`ResumeExecutionCommand` to `UnpauseExecutionCommand`)
- Modify: `packages/syn-adapters/src/syn_adapters/control/commands.py` (`ResumeExecution`)
- Modify: `apps/syn-api/src/syn_api/routes/executions/control.py` (`resume` service fn, `/resume` route)
- Test: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_unpause.py`

**Interfaces:**
- Consumes: the spelling `Unpause` from Task 1.
- Produces: `UnpauseExecutionCommand`, `ExecutionUnpausedEvent` (event_type `"ExecutionUnpaused"`), and the free name `ExecutionResumed` for Task 4.

- [ ] **Step 1: Find every occurrence before changing anything**

Run:
```bash
grep -rIn 'ExecutionResumed\|ResumeExecution\|resume_execution' \
  --include='*.py' --include='*.ts' packages apps | grep -v generated
```
Record the list. Every hit is either renamed in this task or belongs to Task 4's concept and does not exist yet.

- [ ] **Step 2: Write the failing test**

Create `test_unpause.py`:

```python
"""Un-pausing is Unpause, not Resume (ubiquitous language, 2026-09-27).

`resume` now means continuing an Execution that did not finish. This test pins
the other operation to its own name so the two cannot collapse again.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    PauseExecutionCommand,
    UnpauseExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionUnpausedEvent import (
    ExecutionUnpausedEvent,
)

pytestmark = pytest.mark.unit

EXEC = "exec-unpause"


def test_the_event_type_is_unpaused() -> None:
    assert ExecutionUnpausedEvent.event_type == "ExecutionUnpaused"


def test_unpausing_returns_the_same_execution_to_running(started_paused) -> None:  # noqa: ANN001
    """The SAME execution continues: no new id, nothing inherited."""
    aggregate = started_paused
    aggregate.unpause_execution(UnpauseExecutionCommand(execution_id=EXEC, phase_id="plan"))

    assert aggregate.status is ExecutionStatus.RUNNING
    assert aggregate.id == EXEC, "unpausing must not mint a new execution id"


def test_the_old_name_is_gone() -> None:
    """A lingering alias is how one word regains two meanings."""
    import syn_domain.contexts.orchestration.domain.aggregate_execution.commands as commands

    assert not hasattr(commands, "ResumeExecutionCommand"), (
        "ResumeExecutionCommand must not survive: `resume` is the other concept now"
    )
```

Add a `started_paused` fixture in the same file that starts an execution, starts `plan`, and pauses it via `PauseExecutionCommand`.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_unpause.py -v`
Expected: FAIL, `ModuleNotFoundError: ...ExecutionUnpausedEvent`

- [ ] **Step 4: Rename the event**

```bash
git mv packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/ExecutionResumedEvent.py \
       packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/ExecutionUnpausedEvent.py
```

In the moved file, rename the class to `ExecutionUnpausedEvent`, set `event_type` to `"ExecutionUnpaused"`, rename `resumed_at` to `unpaused_at`, and replace the docstring with one that says what it is and why it was renamed:

```python
"""ExecutionUnpaused event - a paused execution returned to running.

Called Unpause and not Resume because `resume` names the other operation:
continuing an execution that did not finish, by starting a new one. The two
shared the word until 2026-09-27 and the ambiguity reached the CLI. See
`docs/architecture/orchestration-ubiquitous-language.md`.
"""
```

- [ ] **Step 5: Rename the command and the handler**

In `commands.py`: `ResumeExecutionCommand` to `UnpauseExecutionCommand`, docstring updated the same way.

In `WorkflowExecutionAggregate.py`: the command handler `resume_execution` to `unpause_execution`, its `@command_handler("ResumeExecutionCommand")` to `"UnpauseExecutionCommand"`, and the apply handler's `@event_sourcing_handler("ExecutionResumed")` to `"ExecutionUnpaused"` with `on_execution_resumed` to `on_execution_unpaused`.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_unpause.py -v`
Expected: PASS

- [ ] **Step 7: Follow the breakage out to the adapters and the API**

Run: `uv run pyright` and fix every reported reference: `syn_adapters/control/commands.py` (`ResumeExecution` to `UnpauseExecution`), `syn_adapters/control/controller.py`, `apps/syn-api/src/syn_api/routes/executions/control.py`.

In `control.py` the service function `resume` becomes `unpause`, and the route becomes:

```python
@router.post("/executions/{execution_id}/unpause", response_model=ControlResponse)
async def unpause_execution_endpoint(execution_id: str) -> ControlResponse:
    """Return a paused execution to running."""
    execution_id = await _resolve_execution_id(execution_id)
    result = await unpause(execution_id)
    return await _handle_control_result(result, "unpause")
```

Keep the old path as an explicit alias so a scripted caller is not broken silently - this is Review Focus item 4:

```python
@router.post(
    "/executions/{execution_id}/resume",
    response_model=ControlResponse,
    deprecated=True,
    summary="Deprecated alias for unpause",
)
async def resume_execution_endpoint_deprecated(execution_id: str) -> ControlResponse:
    """The pre-2026-09-27 name for unpause.

    `resume` now means continuing an execution that did not finish, so this path
    is the old meaning kept alive for one release. It does NOT resume a failed
    execution - `POST /executions/{id}/resume` for that is Task 5's route, and
    the two cannot share a path, which is why this one is deprecated rather than
    reused.
    """
    return await unpause_execution_endpoint(execution_id)
```

**Note for the implementer:** that alias collides with Task 5's route on the same path and method. Resolve it in Task 5 by REMOVING this alias there, and mention the removal in Task 5's commit. Do not leave both.

- [ ] **Step 8: Run the full gates**

Run each and report:
```bash
just vsa-validate
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest -q -m unit
uv run pytest ci/fitness -q
just fitness-check
```
Expected: all green, 0 failures.

- [ ] **Step 9: Commit**

```bash
git add -u && git add packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/ExecutionUnpausedEvent.py \
  packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_unpause.py
git commit -m "refactor(orchestration)!: un-pausing is Unpause, not Resume

Frees the word `resume` for the operation that continues an execution which did
not finish. The rename is free: production holds zero ExecutionPaused and zero
ExecutionResumed events out of 26,917, so no stored stream changes meaning and
no upcaster is needed.

ExecutionResumed -> ExecutionUnpaused, ResumeExecutionCommand ->
UnpauseExecutionCommand, POST /executions/{id}/resume -> /unpause with the old
path kept as a deprecated alias for one release."
```

---

### Task 4: Take the name - the fork concept becomes Resume

**Files:**
- Rename: `.../domain/events/ExecutionForkedEvent.py` to `ExecutionResumedEvent.py`
- Rename: `.../aggregate_execution/fork_rules.py` to `resume_rules.py`
- Rename: `.../aggregate_execution/fork_start.py` to `resume_start.py`
- Rename: `.../slices/execute_workflow/fork_handoff.py` to `resume_handoff.py`
- Rename: `.../slices/start_fork/` to `.../slices/start_resume/` (and the files inside: `ForkStartProcessManager.py` to `ResumeStartProcessManager.py`, `StartForkHandler.py` to `StartResumeHandler.py`)
- Modify: `commands.py`, `value_objects.py`, `start_pins.py`, `WorkflowExecutionAggregate.py`, `replay.py`, `contexts/orchestration/__init__.py`, `domain/events/__init__.py`, `WorkflowExecutionProcessor.py`, `coordinator_service.py`, `_wiring.py`, `_wiring_admission.py`
- Create: `.../aggregate_execution/legacy_event_shapes.py`
- Test: `.../aggregate_execution/test_legacy_event_shapes.py`

**Interfaces:**
- Consumes: the free name from Task 3; the spellings from Task 1.
- Produces: `ResumeExecutionCommand` (the NEW meaning - execution_id, resume_execution_id, override_cancellation, acknowledge_external_effects), `ExecutionResumedEvent` (event_type `"ExecutionResumed"`, fields resume_execution_id, inherited_phases, resume_phase_id, resumed_at, cancellation_overridden, external_effects_acknowledged), `ResumeOrigin` (was `ForkOrigin`), `refuse_resume`, `decide_resume`, `ResumeRefused`/`ResumeAdmitted`, `ResumeStartRecord`.

- [ ] **Step 1: Write the failing test for the legacy-shape hazard**

This is Review Focus items 1 and 2. Create `test_legacy_event_shapes.py`:

```python
"""The string `ExecutionResumed` changed meaning on 2026-09-27.

Before: un-pausing a paused execution (fields phase_id, resumed_at).
After: continuing an execution that did not finish (fields
resume_execution_id, inherited_phases, resume_phase_id).

Production held zero of the old kind when this shipped, but the window between
the merge and the deploy was not closed, and a developer's local stream may
hold either. A payload written under the old meaning must never be read as the
new one: that would make an execution look resumed when nobody resumed it, and
spend its one resume.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.legacy_event_shapes import (
    LegacyEventShapeError,
    classify_resumed_payload,
)

pytestmark = pytest.mark.unit


def test_the_old_unpause_shape_is_recognised_and_refused() -> None:
    old = {"workflow_id": "wf-1", "execution_id": "exec-1", "phase_id": "plan",
           "resumed_at": "2026-09-01T00:00:00Z"}

    with pytest.raises(LegacyEventShapeError, match="un-pausing"):
        classify_resumed_payload(old)


def test_the_new_resume_shape_passes() -> None:
    new = {"workflow_id": "wf-1", "execution_id": "exec-1",
           "resume_execution_id": "exec-2", "inherited_phases": [],
           "resume_phase_id": "plan", "resumed_at": "2026-09-27T00:00:00Z"}

    assert classify_resumed_payload(new) is None


def test_a_pre_rename_forked_payload_upcasts_rather_than_vanishing() -> None:
    """An `ExecutionForked` event from the pre-rename build must still be read.

    Dropping it silently would make its parent look unresumed and admit a
    second resume, which the one-resume rule exists to prevent.
    """
    from syn_domain.contexts.orchestration.domain.aggregate_execution.legacy_event_shapes import (
        upcast_forked_payload,
    )

    forked = {"workflow_id": "wf-1", "execution_id": "exec-1",
              "fork_execution_id": "exec-2", "inherited_phases": [],
              "resume_phase_id": "plan", "forked_at": "2026-09-26T00:00:00Z"}

    upcast = upcast_forked_payload(forked)

    assert upcast["resume_execution_id"] == "exec-2"
    assert upcast["resumed_at"] == "2026-09-26T00:00:00Z"
    assert "fork_execution_id" not in upcast
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_legacy_event_shapes.py -v`
Expected: FAIL, `ModuleNotFoundError: ...legacy_event_shapes`

- [ ] **Step 3: Write the discriminator**

Create `legacy_event_shapes.py`:

```python
"""Reading events whose type name changed meaning (2026-09-27).

`ExecutionResumed` meant un-pausing before this date and means
resume-from-unfinished after it. A type name cannot be trusted alone, so the
payload SHAPE decides, and an ambiguous one is refused rather than guessed.

See `docs/architecture/orchestration-ubiquitous-language.md`.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Present only on the post-rename shape.
_RESUME_MARKER = "resume_execution_id"

#: Present only on the pre-rename unpause shape. `resumed_at` is NOT a
#: discriminator: both shapes carry it.
_UNPAUSE_MARKER = "phase_id"


class LegacyEventShapeError(RuntimeError):
    """A stored payload cannot be read as the type its name now means."""


def classify_resumed_payload(payload: Mapping[str, object]) -> None:
    """Return None when `payload` is a post-rename resume, else raise.

    Refusing is deliberate. Interpreting an un-pause as a resume would record
    that an execution had been resumed when nobody resumed it, and an execution
    may be resumed once - so the mistake is unrecoverable, while a refusal is
    a log line and a fixable migration.
    """
    if _RESUME_MARKER in payload:
        return None
    if _UNPAUSE_MARKER in payload:
        msg = (
            "This ExecutionResumed payload is the pre-2026-09-27 shape, which recorded "
            "un-pausing a paused execution, not resuming an unfinished one. It carries "
            f"{_UNPAUSE_MARKER!r} and no {_RESUME_MARKER!r}. Rename the stored type to "
            "ExecutionUnpaused before replaying it."
        )
        raise LegacyEventShapeError(msg)
    msg = (
        "An ExecutionResumed payload carries neither the resume marker "
        f"{_RESUME_MARKER!r} nor the un-pause marker {_UNPAUSE_MARKER!r}; its meaning "
        "cannot be determined and it is not guessed."
    )
    raise LegacyEventShapeError(msg)


def upcast_forked_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """A pre-rename `ExecutionForked` payload as an `ExecutionResumed` one.

    The concept did not change, only its name, so every field maps one to one.
    """
    upcast = dict(payload)
    if "fork_execution_id" in upcast:
        upcast["resume_execution_id"] = upcast.pop("fork_execution_id")
    if "forked_at" in upcast:
        upcast["resumed_at"] = upcast.pop("forked_at")
    if "cancellation_overridden" not in upcast:
        upcast["cancellation_overridden"] = False
    return upcast
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_legacy_event_shapes.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit the discriminator before the rename**

```bash
git add packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/legacy_event_shapes.py \
        packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_legacy_event_shapes.py
git commit -m "feat(orchestration): decide a renamed event's meaning by payload shape

ExecutionResumed means something different after the rename. The type name
alone cannot say which, so the shape decides and an ambiguous payload is
refused rather than guessed: reading an un-pause as a resume would spend an
execution's one resume on an event nobody wrote."
```

- [ ] **Step 6: Perform the file renames**

```bash
cd packages/syn-domain/src/syn_domain/contexts/orchestration
git mv domain/events/ExecutionForkedEvent.py domain/events/ExecutionResumedEvent.py
git mv domain/aggregate_execution/fork_rules.py domain/aggregate_execution/resume_rules.py
git mv domain/aggregate_execution/fork_start.py domain/aggregate_execution/resume_start.py
git mv slices/execute_workflow/fork_handoff.py slices/execute_workflow/resume_handoff.py
git mv slices/start_fork slices/start_resume
git mv slices/start_resume/ForkStartProcessManager.py slices/start_resume/ResumeStartProcessManager.py
git mv slices/start_resume/StartForkHandler.py slices/start_resume/StartResumeHandler.py
git mv slices/start_resume/test_start_fork.py slices/start_resume/test_start_resume.py
```

- [ ] **Step 7: Rename the identifiers**

Apply this map with `git grep -l <old> | xargs sed -i ''` one entry at a time, checking `git diff` after each. **Exclude** `slices/execute_workflow/handlers/skill_install.py` from every pass: its `GRPC_ENABLE_FORK_SUPPORT` comments are process-fork and must not change.

| Old | New |
|---|---|
| `ExecutionForkedEvent` | `ExecutionResumedEvent` |
| `"ExecutionForked"` | `"ExecutionResumed"` |
| `ForkExecutionCommand` | `ResumeExecutionCommand` |
| `fork_execution` (method) | `resume_execution` |
| `fork_execution_id` | `resume_execution_id` |
| `forked_at` | `resumed_at` |
| `_forked` | `_resumed` |
| `forked_from` | `resumed_from` |
| `ForkOrigin` | `ResumeOrigin` |
| `StartForkCommand` | `StartResumeCommand` |
| `ForkStartRecord` | `ResumeStartRecord` |
| `ForkStartProcessManager` | `ResumeStartProcessManager` |
| `StartForkHandler` | `StartResumeHandler` |
| `ForkStarter` | `ResumeStarter` |
| `refuse_fork_start` | `refuse_resume_start` |
| `refuse_fork` | `refuse_resume` |
| `decide_fork` | `decide_resume` |
| `ForkRefused` / `ForkAdmitted` | `ResumeRefused` / `ResumeAdmitted` |
| `FORKABLE_STATUSES` | `RESUMABLE_STATUSES` |
| `fork_start_command` | `resume_start_command` |
| `start_fork` | `start_resume` |
| `fork_rules` | `resume_rules` |
| `fork_handoff` | `resume_handoff` |
| `INHERITED_PHASE_OWNERS` | unchanged |

- [ ] **Step 8: Wire the discriminator into replay**

In `ExecutionResumedEvent.py`, the existing `@model_validator(mode="before")` that restores owners must first classify:

```python
    @model_validator(mode="before")
    @classmethod
    def _reject_the_old_meaning(cls, data: object) -> object:
        """An `ExecutionResumed` payload from before the rename is not this event."""
        if isinstance(data, dict):
            classify_resumed_payload(data)
        return payload_with_owners_restored(data)
```

Note `classify_resumed_payload` takes a Mapping and this file may not import `collections.abc` (Global Constraints). Call it with a `dict` check as above and keep the Mapping annotation inside `legacy_event_shapes.py`.

- [ ] **Step 9: Run everything and fix the fallout**

```bash
uv run ruff check . --fix && uv run ruff format .
uv run pyright
uv run pytest -q -m unit
```
Expected after fixes: pyright 0 errors, unit 0 failures.

- [ ] **Step 10: Prove the renamed fixes are still load-bearing**

The three defect fixes must still be covered. Commit first, then for each mutation apply it, run the FULL suite (`-m unit`, not a selection - a narrow run cannot prove a survival), record the failures, and restore:

```bash
git add -u && git commit -m "refactor(orchestration)!: the fork concept is Resume"
```

| Mutation | Expected |
|---|---|
| `resume_handoff.py`: `artifacts=self._collector()` to `artifacts=None` in `phase_workspace.py` | at least 3 failures |
| `value_objects.py`: `owner_of` returns `self.parent_execution_id` always | at least 5 failures, incl. a grandchild test |
| `ResumeStartProcessManager`: `_record_task_failure` body to `return` | at least 5 failures |
| `_write_is_allowed`: `only_over` branch to `if False:` | at least 5 failures |

- [ ] **Step 11: Run the full gates and commit**

```bash
just vsa-validate && uv run pytest ci/fitness -q && just fitness-check
git add -u
git commit -m "refactor(orchestration)!: the fork concept is Resume

ExecutionForked -> ExecutionResumed, and every identifier with it. The concept
did not change: a new execution inheriting the completed prefix of one that did
not finish. Only its name was wrong, and the wrong name spent the word `fork`,
which now means what it should: copying any prior execution from a chosen
completed phase (see the Fork issue).

A pre-rename ExecutionForked payload upcasts field for field. Process-fork
references in skill_install.py are untouched: GRPC_ENABLE_FORK_SUPPORT is
unrelated to this vocabulary."
```

---

### Task 5: The API surface

**Files:**
- Rename: `apps/syn-api/src/syn_api/routes/executions/fork.py` to `resume.py`
- Modify: `apps/syn-api/src/syn_api/routes/executions/__init__.py`
- Modify: `apps/syn-api/src/syn_api/routes/executions/control.py` (REMOVE Task 3's deprecated `/resume` alias)
- Modify: `scripts/extract_openapi.py` (the `fork` tag description becomes `resume`)
- Rename: `apps/syn-api/tests/test_fork_endpoint.py` to `test_resume_endpoint.py`
- Test: same file, plus a new case for Review Focus item 3

**Interfaces:**
- Consumes: `ResumeExecutionCommand`, `ExecutionResumedEvent`, `refuse_resume_start`, `inherited_outputs` from Task 4.
- Produces: `POST /executions/{execution_id}/resume`, `ResumeRequest`, `ResumeResponse` (fields: source_execution_id, execution_id, resume_phase_id, inherited_phase_ids, cancellation_overridden, external_effects_acknowledged).

- [ ] **Step 1: Write the failing test**

Add to the renamed `test_resume_endpoint.py`:

```python
async def test_the_old_fork_path_is_gone_not_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus 3: a caller on the old path gets a 404, never a 500.

    The route was never deployed, so no client depends on it - but a developer's
    script might, and a 500 would send them debugging the server.
    """
    from syn_api.main import create_app
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/executions/exec-1/fork", json={})

    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/syn-api/tests/test_resume_endpoint.py -v`
Expected: FAIL on import (the module is still `test_fork_endpoint.py`) or on the route still existing.

- [ ] **Step 3: Rename the route module and its symbols**

```bash
git mv apps/syn-api/src/syn_api/routes/executions/fork.py \
       apps/syn-api/src/syn_api/routes/executions/resume.py
git mv apps/syn-api/tests/test_fork_endpoint.py apps/syn-api/tests/test_resume_endpoint.py
```

In `resume.py`: `ForkRequest` to `ResumeRequest`, `ForkResponse` to `ResumeResponse`, `fork()` to `resume()`, `fork_execution_endpoint` to `resume_execution_endpoint`, path to `/executions/{execution_id}/resume`, tag to `resume`, `_free_child_id` to `_free_resume_id`, and `parent_execution_id` in the response to `source_execution_id`. Update the module docstring to distinguish resume from unpause and to cite the ubiquitous language file.

- [ ] **Step 4: Remove Task 3's alias**

Delete `resume_execution_endpoint_deprecated` from `control.py`. Both cannot own `POST /executions/{id}/resume`, and the new meaning wins. `control.py` keeps only `/unpause`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest apps/syn-api/tests/test_resume_endpoint.py -v`
Expected: PASS, 18 tests

- [ ] **Step 6: Regenerate and check drift**

```bash
just codegen
just check-openapi-drift
```
Expected: no drift; `/executions/{execution_id}/resume` present; `/fork` absent.

- [ ] **Step 7: Run the full gates and commit**

```bash
git add -u && git add apps/syn-api/src/syn_api/routes/executions/resume.py apps/syn-api/tests/test_resume_endpoint.py
git commit -m "refactor(api)!: POST /executions/{id}/resume replaces /fork

And takes the path from control's un-pause, which moved to /unpause in the
previous commit - the two meanings cannot share a path, so the one that means
'continue what did not finish' keeps the word."
```

---

### Task 6: The CLI surface

**Files:**
- Modify: `apps/syn-cli-node/src/commands/execution.ts` (`forkCommand` to `resumeCommand`)
- Modify: `apps/syn-cli-node/src/commands/control.ts` (`resumeCommand` to `unpauseCommand`, with `resume` as a hidden alias)
- Create: `apps/syn-cli-node/tests/commands/resume.test.ts`

**Interfaces:**
- Consumes: the generated types from Task 5's `just codegen`.
- Produces: `syn execution resume <id>`, `syn control unpause <id>`.

- [ ] **Step 1: Write the failing test**

Create `resume.test.ts` covering Review Focus item 4 and the refusal paths:

```typescript
import { describe, expect, it } from "vitest";
import { executionGroup } from "../../src/commands/execution.js";
import { controlGroup } from "../../src/commands/control.js";

describe("the resume verb belongs to execution", () => {
  it("syn execution resume exists", () => {
    expect(executionGroup.commands.map((c) => c.name)).toContain("resume");
  });

  it("syn execution fork does not, because fork is reserved", () => {
    expect(executionGroup.commands.map((c) => c.name)).not.toContain("fork");
  });
});

describe("un-pausing is called unpause", () => {
  it("syn control unpause exists", () => {
    expect(controlGroup.commands.map((c) => c.name)).toContain("unpause");
  });

  it("syn control resume still routes, so a script does not break silently", () => {
    const names = controlGroup.commands.flatMap((c) => [c.name, ...(c.aliases ?? [])]);
    expect(names).toContain("resume");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/commands/resume.test.ts`
Expected: FAIL, `expected [ 'list', 'show', 'fork' ] to contain 'resume'`

- [ ] **Step 3: Rename the execution command**

In `execution.ts`: `forkCommand` to `resumeCommand`, `name: "resume"`, description `"Resume a failed execution from the first phase that did not finish"`. Output labels change `Forked` to `Resumed` and `New execution` stays. Path becomes `/executions/{execution_id}/resume`.

- [ ] **Step 4: Rename the control command with an alias**

In `control.ts`: `resumeCommand` to `unpauseCommand`, `name: "unpause"`, and add `aliases: ["resume"]` so an existing script keeps working. Its description states it returns a PAUSED execution to running, and points at `syn execution resume` for a failed one.

If `CommandDef` has no `aliases` field, add it to `apps/syn-cli-node/src/framework/command.ts` and honour it in the group's lookup - a one-field change, and the alternative is breaking users silently.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/syn-cli-node && pnpm vitest run tests/commands/resume.test.ts`
Expected: PASS, 4 tests

- [ ] **Step 6: Typecheck, build, and check the help text by hand**

```bash
cd apps/syn-cli-node && pnpm exec tsc --noEmit && pnpm build
node dist/syn.js execution resume --help
node dist/syn.js control unpause --help
```
Expected: both render; `execution resume` shows both flags.

- [ ] **Step 7: Commit**

```bash
git add -u && git add apps/syn-cli-node/tests/commands/resume.test.ts
git commit -m "refactor(cli)!: syn execution resume, syn control unpause

`resume` now means one thing. `syn control resume` keeps working as an alias so
a script does not break silently, and its help points at the other verb."
```

---

### Task 7: The documentation

**Files:**
- Rename: `apps/syn-docs/content/docs/guide/resuming-executions.mdx` (path already correct; content updated)
- Modify: `apps/syn-docs/content/docs/guide/meta.json` (unchanged if the slug is unchanged)
- Delete: `apps/syn-docs/content/docs/api/fork.mdx`; regenerate as `resume.mdx`
- Modify: `apps/syn-docs/content/docs/api/meta.json`, `.../cli/execution.mdx`, `.../cli/control.mdx`
- Modify: `docs/adrs/ADR-014-workflow-execution-model.md` section 7

**Interfaces:**
- Consumes: the vocabulary from Task 1; the surfaces from Tasks 5 and 6.
- Produces: nothing code depends on.

- [ ] **Step 1: Update ADR-014 section 7 in place**

Per repo convention ADRs are revised, never superseded. Retitle section 7 to "Resuming a terminal execution is a NEW EXECUTION, not a mutation", replace `fork` with `resume` throughout, and add a paragraph recording the rename, the date, and that `fork` is now reserved for the copy-from-any-phase operation with a link to its issue.

- [ ] **Step 2: Update the guide**

In `resuming-executions.mdx`: every `fork`/`forked` becomes `resume`/`resumed`; `syn execution fork` becomes `syn execution resume`; the resume-vs-unpause table replaces the resume-vs-fork one:

```markdown
| You want | Command | What happens |
| --- | --- | --- |
| Continue a **paused** run | `syn control unpause <id>` | The same execution carries on |
| Pick up a run that **did not finish** | `syn execution resume <id>` | A **new** execution inherits the completed phases |
```

Add a short section naming `Fork` as reserved and not yet available, linking the issue, so a reader who wants to branch a completed run is not left guessing.

- [ ] **Step 3: Regenerate the reference docs**

```bash
just codegen
```
Expected: `api/resume.mdx` created, `api/fork.mdx` gone, `cli/execution.mdx` and `cli/control.mdx` updated.

- [ ] **Step 4: Fix the API nav**

In `apps/syn-docs/content/docs/api/meta.json`, replace `"fork"` with `"resume"`.

- [ ] **Step 5: Verify the docs build and the words are gone**

```bash
just check-docs-content
cd apps/syn-docs && pnpm build
grep -rn 'execution fork\|/fork' content/docs/ | grep -v 'Fork' || echo "clean"
```
Expected: typography passes, build succeeds, no stale `/fork` references outside the reserved-word explanation.

- [ ] **Step 6: Commit**

```bash
git add -u && git add apps/syn-docs/content/docs/api/resume.mdx
git commit -m "docs: resume is resume everywhere, and fork is documented as reserved

ADR-014 section 7 revised in place per convention. The guide leads with the
resume-versus-unpause distinction, which is the one an operator will otherwise
get wrong, and says plainly that Fork is a reserved word for work not yet
built."
```

---

### Task 8: The guard that keeps the word reserved

**Files:**
- Create: `ci/fitness/code_quality/test_reserved_domain_words.py`

**Interfaces:**
- Consumes: the allow-list of legitimate process-fork sites.
- Produces: a failing gate when `fork` returns to the orchestration context.

- [ ] **Step 1: Write the failing test**

```python
"""`fork` is reserved in the orchestration context until the Fork feature ships.

Review Focus 5. The word was spent once on the operation now called resume; a
grep is what stops it being spent again before the real capability exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_CONTEXT = Path("packages/syn-domain/src/syn_domain/contexts/orchestration")

#: Process-fork, unrelated to the domain vocabulary. Each entry is a real file
#: and a reason; an entry whose file disappears fails the staleness test below.
_ALLOWED = {
    "slices/execute_workflow/handlers/skill_install.py": "GRPC_ENABLE_FORK_SUPPORT, the grpc-fork-under-uvloop crash",
}

_FORK = re.compile(r"\bfork", re.IGNORECASE)


def _offenders() -> list[str]:
    hits: list[str] = []
    for path in _CONTEXT.rglob("*.py"):
        rel = path.relative_to(_CONTEXT).as_posix()
        if rel in _ALLOWED:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if _FORK.search(line):
                hits.append(f"{rel}:{number}: {line.strip()}")
    return hits


def test_fork_does_not_appear_in_the_orchestration_context() -> None:
    offenders = _offenders()
    assert not offenders, (
        "`fork` is reserved for the copy-from-any-phase operation and is not built yet. "
        "An operation that continues unfinished work is a resume. See "
        "docs/architecture/orchestration-ubiquitous-language.md.\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("rel", sorted(_ALLOWED))
def test_every_allowed_file_still_exists(rel: str) -> None:
    """A stale allow-list entry hides a real offender behind a dead path."""
    assert (_CONTEXT / rel).is_file(), f"{rel} is allow-listed and gone; remove the entry"
```

- [ ] **Step 2: Run test to verify it fails before Task 4 is complete, passes after**

Run: `uv run pytest ci/fitness/code_quality/test_reserved_domain_words.py -v`
Expected: PASS if Tasks 3-7 are done. If it FAILS, the offenders it names are renames Task 4 missed - fix them, do not extend the allow-list.

- [ ] **Step 3: Commit**

```bash
git add ci/fitness/code_quality/test_reserved_domain_words.py
git commit -m "test(fitness): keep `fork` reserved until the feature claims it

The word was spent once on the operation now called resume. This fails the
build if it reappears in the orchestration context outside the two
process-fork comments, which are allow-listed by path and reason."
```

---

### Task 9: File the Fork issue

**Files:** none. Produces a GitHub issue.

- [ ] **Step 1: Write the issue body**

Create it with `gh issue create --title "Fork: copy any execution from a chosen completed phase" --body-file <path>`, with this content:

```markdown
`resume` continues an execution that did not finish, deriving where to start.
**Fork** is the other operation, and it does not exist: copying any execution
that has completed at least one phase - INCLUDING a `completed` one - into a
new execution that starts from a CHOSEN completed phase.

Definitions: `docs/architecture/orchestration-ubiquitous-language.md`.

## Why resume cannot cover it

Two things are missing, not one:

1. **A fork point.** Resume derives its start: the first unfinished phase. A
   completed execution has none, and `refuse_resume_start` correctly refuses it
   with "no unfinished phase to resume at". A fork must be TOLD where to start.
2. **Overrides.** Forking a completed run and changing nothing replays it at
   full cost. The value is varying something - a model, a prompt - against the
   same baseline. The resume API accepts no overrides and the child copies the
   parent's pins exactly, deliberately.

## What it needs

- `RESUMABLE_STATUSES` gains a fork counterpart that includes `COMPLETED`, with
  the "at least one completed phase" rule.
- A fork point parameter naming a completed phase; everything from that phase
  onward is re-run and is NOT inherited.
- Overrides recorded ON the event, so the difference between a parent and a
  fork is a fact in the stream rather than something reconstructed. This is
  what makes eval comparisons attributable.
- The inheritance rule already generalises: `InheritedPhase` carries the
  execution that produced each phase, so a fork of a fork resolves artifacts
  from the right ancestor.

## Why it matters beyond convenience

This is the primitive the Eval concept sits on: an Eval is a tag plus an
aggregate, and "same commit, different model" needs a fork point AND an
override. Blocked on nothing except this feature - and on the workspace
cloning the recorded commit rather than the default branch, so that two runs
can be asserted to have seen the same code.

## Naming

"Fork" rather than "branch" because the new execution COPIES recorded state
rather than diverging a shared history. "Branch" is left undefined in the
vocabulary; if a chat-style operation is ever wanted, it can take that word.
```

- [ ] **Step 2: Cross-link it**

Add the issue number to the `## Fork` section of
`docs/architecture/orchestration-ubiquitous-language.md` and to ADR-014 section 7, replacing "the Fork issue" with the real reference. Commit.

---

## Self-Review

**Spec coverage.** Decision 1 (full rename) is Tasks 3-7. Decision 2 (resume applies to unfinished) is Task 1's definition plus the unchanged `RESUMABLE_STATUSES`. Decision 3 (fork spec) is Task 9. Decision 4 (incumbent moves) is Task 3. Decision 5 (ubiquitous language, AGENTS.md) is Tasks 1 and 2. No gaps.

**Placeholders.** None: every code step carries the code, every rename carries its old and new name, the identifier table is exhaustive, and the issue body is written out rather than described.

**Type consistency.** `ResumeExecutionCommand` is used for the NEW meaning in Task 4 and consumed under that name in Task 5; Task 3 removes the old `ResumeExecutionCommand` before Task 4 creates it, which is why Task 3 runs first and why its test asserts the old name is absent. `ResumeOrigin`, `ResumeStartRecord`, `refuse_resume_start` and `decide_resume` are introduced in Task 4 and used in Tasks 5, 6 and 8 under exactly those names. `ResumeResponse.source_execution_id` is named in Task 5's Interfaces and used in Task 6's output.

**Review Focus coverage.** Item 1 and 2 are Task 4 Step 1. Item 3 is Task 5 Step 1. Item 4 is Task 6 Step 1 and the alias in Task 6 Step 4. Item 5 is Task 8.

## Risks the executor must not smooth over

- **The rename is only free while no events exist.** Measured 2026-09-27: zero `ExecutionPaused`, zero `ExecutionResumed`, zero `ExecutionForked` in production (26,917 events total; the fork route returns 404 on the deployment). If any appear before this merges, Task 4's discriminator is what saves the replay - do not delete it as unnecessary.
- **`git mv` of `slices/start_fork` changes a slice path.** `vsa-validate` has opinions about slice structure; run it immediately after Step 6 of Task 4, not at the end.
- **Four of five bounded contexts still have no vocabulary file.** Out of scope here, stated in AGENTS.md so it is visible rather than forgotten.
