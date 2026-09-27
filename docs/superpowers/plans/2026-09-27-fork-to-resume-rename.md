# Fork-to-Resume Rename and Orchestration Ubiquitous Language: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `resume` the single name for continuing work that did not finish, free the word `fork` to mean copying any prior execution, and write the orchestration context's ubiquitous language down so the distinction survives.

**Architecture:** Three renames in dependency order - free the `resume` name from its current pause/resume holder, take it for the execution-continuation concept, then rename the surfaces. A payload-shape discriminator protects the one real hazard: the string `ExecutionResumed` changes meaning, so an event written under the old meaning must never be silently read as the new one. The definitions land first and act as this plan's own spec.

**Tech Stack:** Python 3.14, Pydantic v2, FastAPI, event-sourcing-platform (ESP) SDK, Node/TypeScript CLI, Fumadocs (Next.js), pytest, ruff, pyright, vsa, APSS fitness.

**Spec:** This document's "Decisions" section below. The owner specified the vocabulary directly in conversation on 2026-09-27; no separate spec doc exists, so the decisions are recorded here and the ubiquitous language file created in Task 1 becomes the durable canonical source.

## Decisions (the spec)

Answered by the owner on 2026-09-27.

1. **Full rename.** The domain, the events, the API and the CLI. Naming alignment is a maintainability property, and `fork` must be reserved as a canonical word in the bounded context's vocabulary.
2. **`resume`** applies to an execution that did not finish: `failed`, `interrupted`, or `cancelled` (the last with an explicit override). It is the glossary term and the domain name.
3. **`fork`** applies to any execution with at least one completed phase - including a `completed` one - copied from a CHOSEN completed phase. **Not built here.** Task 10 files it.
4. **Pause is deleted, not renamed.** There is no working pause to preserve. Measured: zero `ExecutionPaused` events of 26,917 in production, and nothing in the execution path ever reads `ExecutionStatus.PAUSED` - the processor observes `CANCELLED` (WorkflowExecutionProcessor.py:374) and nothing else, so a paused execution keeps running. Cancel is the working mechanism and is sufficient. An earlier draft invented `unpause` to dodge a name collision with a feature that does not function; deleting is simpler and frees `resume` outright.
5. **Every bounded context owns a ubiquitous language file**, and a QA check enforces it. This is standard DDD practice and was missing entirely: `es-glossary.md` covers ESP patterns, the ESP submodule has its own, and none of the five contexts had a vocabulary.
6. **File naming standard: `<bounded-context>-ubiquitous-language.md`**, context name FIRST. So a search returns files whose names say which context they belong to, rather than five identically-named files. Location: `docs/architecture/`.
7. **ESP must state the convention**, since this is an ESP-based system and the expectation is inherited from it. Task 10 opens the submodule note and an issue for a platform-level validator.

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

### Task 1: The validator - every bounded context owns a vocabulary

The QA check comes first, so the four missing vocabularies fail loudly rather than being forgotten.

**Files:**
- Create: `ci/fitness/code_quality/test_ubiquitous_language.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the file-naming standard `<bounded-context>-ubiquitous-language.md` under `docs/architecture/`, enforced. Task 2 satisfies it.

- [ ] **Step 1: Write the failing test**

```python
"""Every bounded context owns a ubiquitous language file.

Standard DDD practice, and inherited from the event-sourcing platform this
system is built on: a bounded context is DEFINED by the language spoken inside
it, so that language is an artifact and not folklore.

Naming standard: `<bounded-context>-ubiquitous-language.md`, context name first,
so a search returns files whose names say which context they belong to instead
of five identically-named ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_CONTEXTS = Path("packages/syn-domain/src/syn_domain/contexts")
_DOCS = Path("docs/architecture")

#: Not a bounded context: shared value objects with no domain of their own.
_NOT_A_CONTEXT = {"_shared"}


def _bounded_contexts() -> list[str]:
    return sorted(
        d.name
        for d in _CONTEXTS.iterdir()
        if d.is_dir() and not d.name.startswith("__") and d.name not in _NOT_A_CONTEXT
    )


def test_there_are_contexts_to_check() -> None:
    """A discovery bug that finds nothing would make every test below vacuous."""
    assert len(_bounded_contexts()) >= 5, _bounded_contexts()


@pytest.mark.parametrize("context", _bounded_contexts())
def test_every_context_has_a_vocabulary(context: str) -> None:
    doc = _DOCS / f"{context}-ubiquitous-language.md"
    assert doc.is_file(), (
        f"bounded context {context!r} has no ubiquitous language file. "
        f"Expected {doc}. See AGENTS.md, 'Ubiquitous Language'."
    )


@pytest.mark.parametrize("context", _bounded_contexts())
def test_every_vocabulary_names_its_context(context: str) -> None:
    """A file that does not say which context it speaks for invites drift."""
    doc = _DOCS / f"{context}-ubiquitous-language.md"
    if not doc.is_file():
        pytest.skip("covered by test_every_context_has_a_vocabulary")
    head = doc.read_text()[:400]
    assert context in head, f"{doc} must name {context!r} near the top"


def test_no_vocabulary_is_orphaned() -> None:
    """A vocabulary for a context that no longer exists is stale documentation."""
    contexts = set(_bounded_contexts())
    orphans = [
        f.name
        for f in _DOCS.glob("*-ubiquitous-language.md")
        if f.name.removesuffix("-ubiquitous-language.md") not in contexts
    ]
    assert not orphans, f"vocabularies with no bounded context: {orphans}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest ci/fitness/code_quality/test_ubiquitous_language.py -v`
Expected: FAIL for all five contexts, each naming the file it wants.

- [ ] **Step 3: Commit the validator red**

The gate is the deliverable; it is committed before the documents so the gap is on record.

```bash
git add ci/fitness/code_quality/test_ubiquitous_language.py
git commit -m "test(fitness): require a ubiquitous language file per bounded context

Standard DDD practice, inherited from the ESP, and absent for all five
contexts. Naming standard is <bounded-context>-ubiquitous-language.md so a
search says which context each file speaks for. Red until Task 2."
```

---

### Task 2: Write the five vocabularies

**Files:**
- Create: `docs/architecture/orchestration-ubiquitous-language.md` (full)
- Create: `docs/architecture/agent_sessions-ubiquitous-language.md`
- Create: `docs/architecture/github-ubiquitous-language.md`
- Create: `docs/architecture/artifacts-ubiquitous-language.md`
- Create: `docs/architecture/organization-ubiquitous-language.md`
- Modify: `docs/architecture/README.md`, `docs/architecture/es-glossary.md`

**Interfaces:**
- Consumes: the naming standard from Task 1.
- Produces: the canonical spellings later tasks rename to - `Resume`, `Fork` (reserved), `Inherited Phase`, `Resume Phase`, `Pin`, `Admission`.

**Note on the four non-orchestration files.** Write them from the code that exists, not from imagination: read each context's `domain/` aggregates and events and define the terms actually used. Where a term's meaning is genuinely unclear from the code, write the entry with an explicit `**Unclear:**` line naming the question rather than inventing a definition. A vocabulary that guesses is worse than one that admits a gap.

- [ ] **Step 1: Write the orchestration vocabulary**

Create `docs/architecture/orchestration-ubiquitous-language.md` with the full content given in the appendix at the end of this plan ("Appendix A: orchestration vocabulary"). It defines Execution, Phase, Workflow, Resume, Fork (reserved), Inherited Phase, Resume Phase, Pin, Admission, and a "Words we do not use" section covering Branch, Retry and process-fork.

- [ ] **Step 2: Write the other four, from their code**

For each of `agent_sessions`, `github`, `artifacts`, `organization`:

Run first: `ls packages/syn-domain/src/syn_domain/contexts/<ctx>/domain/` and read the aggregates and events. Then write the file with this shape:

```markdown
# Ubiquitous Language: <context>

## Purpose

The vocabulary of the `<context>` bounded context. These words have exactly
these meanings in code, in the API, in the CLI and in conversation. Where a term
here disagrees with any other document, this one is canonical.

For event-sourcing patterns - Event, Aggregate, Projection - see
`es-glossary.md`. A term belongs here when it names something this context's
users talk about, and there when it names a mechanism the platform provides.

Every bounded context has one of these. See AGENTS.md, "Ubiquitous Language".

---

## <Term>

<What it is, in the context's own language. What it is NOT, where a
neighbouring term could be confused with it.>
```

Minimum coverage per context, from the aggregates that exist:
- `agent_sessions`: Session, Operation, Token Usage, Subagent
- `github`: Installation, Trigger Rule, Normalized Event, Dedup Key, Check Run
- `artifacts`: Artifact, Phase Output File, Primary Deliverable
- `organization`: Organization, System, Repo

- [ ] **Step 3: Run test to verify it passes**

Run: `uv run pytest ci/fitness/code_quality/test_ubiquitous_language.py -v`
Expected: PASS for all five contexts.

- [ ] **Step 4: Link them from both neighbours**

In `docs/architecture/README.md`, add a section:

```markdown
### Ubiquitous Language

One per bounded context, canonical for that context's domain terms:

- [orchestration](orchestration-ubiquitous-language.md) - Execution, Phase, Resume, Fork, Pin
- [agent_sessions](agent_sessions-ubiquitous-language.md) - Session, Operation, Subagent
- [github](github-ubiquitous-language.md) - Installation, Trigger Rule, Dedup Key
- [artifacts](artifacts-ubiquitous-language.md) - Artifact, Phase Output File
- [organization](organization-ubiquitous-language.md) - Organization, System, Repo

`es-glossary.md` covers event-sourcing patterns, not domain terms.
```

In `es-glossary.md`, under `## Purpose`:

```markdown
This glossary covers event-sourcing PATTERNS. For the domain vocabulary of a
bounded context - what an Execution or a Resume is - see that context's file,
named `<bounded-context>-ubiquitous-language.md` in this directory.
```

- [ ] **Step 5: Run the docs gate and commit**

```bash
just check-docs-content
git add docs/architecture/
git commit -m "docs(architecture): a ubiquitous language for all five bounded contexts

None existed. The orchestration one is written in full - it is the spec for the
fork-to-resume rename - and the other four define the terms their code already
uses, with explicit Unclear markers where the code did not settle a meaning
rather than inventing one."
```

---

### Task 3: Explain the convention in AGENTS.md

**Files:**
- Modify: `AGENTS.md` (after `### Bounded Contexts & Aggregates (ADR-020)`, which ends at line 249)
- Modify: `ci/fitness/code_quality/test_ubiquitous_language.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_agents_md_explains_the_convention() -> None:
    """A convention nobody is told about is not a convention.

    AGENTS.md is the primary context every agent and contributor reads.
    """
    agents = Path("AGENTS.md").read_text()
    assert "Ubiquitous Language" in agents
    assert "-ubiquitous-language.md" in agents, "AGENTS.md must state the naming standard"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest ci/fitness/code_quality/test_ubiquitous_language.py::test_agents_md_explains_the_convention -v`
Expected: FAIL

- [ ] **Step 3: Add the section**

```markdown
### Ubiquitous Language

Every bounded context owns a written vocabulary, and it is canonical. This is
inherited from the event-sourcing platform this system is built on: a bounded
context is defined by the language spoken inside it, so that language is an
artifact, not folklore.

**File naming standard:** `docs/architecture/<bounded-context>-ubiquitous-language.md`.
Context name FIRST, so a search returns files whose names say which context they
speak for rather than five identically-named ones.

| Scope | Document | Covers |
|---|---|---|
| ESP patterns | `docs/architecture/es-glossary.md` | Event, Aggregate, Projection, Processor |
| Event store | `lib/event-sourcing-platform/docs-site/docs/event-store/concepts/ubiquitous-language.md` | the store's own Axon-aligned terms |
| Each context | `docs/architecture/<context>-ubiquitous-language.md` | that context's domain terms |

**Rules:**

- A domain term used in code, the API or the CLI MUST be defined in its
  context's vocabulary. `ci/fitness/code_quality/test_ubiquitous_language.py`
  fails when a context has no file, when a file names no context, or when a
  file outlives its context.
- One word, one meaning, per context. `resume` means continuing an execution
  that did not finish; there is no other resume.
- A word RESERVED for unbuilt work is still defined, and says it is unbuilt.
  `Fork` is reserved this way.
- Where the code does not settle a term's meaning, the entry says
  `**Unclear:**` and names the question. A vocabulary that guesses is worse
  than one that admits a gap.
```

- [ ] **Step 4: Run to verify it passes, then commit**

```bash
uv run pytest ci/fitness/code_quality/test_ubiquitous_language.py -v
git add AGENTS.md ci/fitness/code_quality/test_ubiquitous_language.py
git commit -m "docs(agents): the ubiquitous language convention and its naming standard"
```

---

### Task 4: Delete the pause noise

Pause is write-only: it records an event and nothing in the execution path ever observes `ExecutionStatus.PAUSED`, so a paused execution keeps running. Cancel is the working mechanism. Deleting it frees the word `resume` outright.

**Files:**
- Delete: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/ExecutionPausedEvent.py`
- Delete: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/ExecutionResumedEvent.py`
- Modify: `.../domain/events/__init__.py`, `.../aggregate_execution/commands.py` (drop `PauseExecutionCommand`, `ResumeExecutionCommand`), `.../aggregate_execution/WorkflowExecutionAggregate.py` (drop `pause_execution`, `resume_execution`, their apply handlers, and `ExecutionStatus.PAUSED` from `accepts_control`)
- Modify: `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/value_objects.py` (drop `PAUSED` from `ExecutionStatus`)
- Modify: `packages/syn-adapters/src/syn_adapters/control/commands.py`, `.../control/controller.py`, `.../control/__init__.py`, `.../projections/manager_event_map.py`
- Modify: `apps/syn-api/src/syn_api/routes/executions/control.py` (drop `pause`, `resume`, both routes)
- Modify: `apps/syn-cli-node/src/commands/control.ts` (drop `pauseCommand`, `resumeCommand`)
- Test: `.../aggregate_execution/test_pause_is_gone.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the free names `resume_execution`, `ResumeExecutionCommand`, `ExecutionResumed`, `/executions/{id}/resume` for Task 5.

- [ ] **Step 1: Confirm the premise before deleting anything**

Run and record:
```bash
grep -rIn 'ExecutionStatus.PAUSED' --include='*.py' packages apps | grep -v test
```
Expected: three hits, all inside `WorkflowExecutionAggregate.py` (the `accepts_control` check and the apply handler). If a hit appears in the execution path, **stop**: pause does something and this task's premise is wrong.

- [ ] **Step 2: Write the failing test**

```python
"""Pause is deleted. Cancel is the mechanism that works.

Pause recorded an event and queued a signal that nothing consumed: the
processor observes CANCELLED and never PAUSED, so a paused execution kept
running. Zero ExecutionPaused events existed in production across 26,917.
Keeping it would have cost the word `resume`, which now names the operation
that continues an execution which did not finish.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution import commands
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)

pytestmark = pytest.mark.unit


def test_the_status_is_gone() -> None:
    assert not hasattr(ExecutionStatus, "PAUSED"), (
        "a status nothing observes is a status that lies about the run"
    )


@pytest.mark.parametrize("name", ["PauseExecutionCommand", "ResumeExecutionCommand"])
def test_the_pause_commands_are_gone(name: str) -> None:
    """`ResumeExecutionCommand` is reintroduced in the next task with the OTHER
    meaning; it must not survive this one with the old one."""
    assert not hasattr(commands, name), f"{name} must not survive the pause deletion"


def test_cancel_survives() -> None:
    assert hasattr(commands, "CancelExecutionCommand")
    assert ExecutionStatus.CANCELLED.value == "cancelled"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest .../test_pause_is_gone.py -v`
Expected: FAIL, `a status nothing observes is a status that lies about the run`

- [ ] **Step 4: Delete, following pyright out**

```bash
git rm packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/ExecutionPausedEvent.py        packages/syn-domain/src/syn_domain/contexts/orchestration/domain/events/ExecutionResumedEvent.py
uv run pyright
```
Remove every reference pyright reports, in this order: events `__init__`, aggregate handlers and commands, `ExecutionStatus.PAUSED`, the adapters, the API routes, the CLI commands. `manager_event_map.py` loses its `ExecutionPaused`/`ExecutionResumed` rows.

Leave untouched: `MaintenancePausedError` and the maintenance admission gate, and the resume-start record's `"paused"` status - both are different concepts.

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest .../test_pause_is_gone.py -v` then `uv run pytest -q -m unit`
Expected: the new tests pass; any other failure is a real reference to remove, not a reason to keep pause.

- [ ] **Step 6: Regenerate and check the surfaces**

```bash
just codegen && just check-openapi-drift
cd apps/syn-cli-node && pnpm exec tsc --noEmit && cd ../..
```
Expected: no drift, CLI typechecks, `/pause` and control's `/resume` gone from the spec.

- [ ] **Step 7: Run the full gates and commit**

```bash
just vsa-validate && uv run pytest ci/fitness -q && just fitness-check
git add -u && git add packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_execution/test_pause_is_gone.py
git commit -m "refactor(orchestration)!: delete pause, which never did anything

Measured before deleting: zero ExecutionPaused events of 26,917 in production,
and nothing in the execution path reads ExecutionStatus.PAUSED - the processor
observes CANCELLED (WorkflowExecutionProcessor.py:374) and nothing else. A
paused execution kept running, so the feature misled anyone who tried it.

Cancel is the working mechanism and is sufficient. Deleting frees the word
`resume` for the operation that continues an execution which did not finish,
rather than inventing `unpause` to dodge a collision with a feature that does
not function.

Maintenance pause and the resume-start record's paused status are different
concepts and are untouched. Pausing an execution for real is filed separately:
it requires the processor to observe the status, which was never written."
```

---

### Task 5: Take the name - the fork concept becomes Resume

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
- Consumes: the free names from Task 4 (pause deleted); the spellings from Task 2.
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

### Task 6: The API surface

**Files:**
- Rename: `apps/syn-api/src/syn_api/routes/executions/fork.py` to `resume.py`
- Modify: `apps/syn-api/src/syn_api/routes/executions/__init__.py`
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

The path is free because Task 4 deleted control's pause/resume, which never
functioned. One route, one meaning."
```

---

### Task 7: The CLI surface

**Files:**
- Modify: `apps/syn-cli-node/src/commands/execution.ts` (`forkCommand` to `resumeCommand`)
- Create: `apps/syn-cli-node/tests/commands/resume.test.ts`

**Interfaces:**
- Consumes: the generated types from Task 5's `just codegen`.
- Produces: `syn execution resume <id>`. `syn control` no longer has pause or resume (deleted in Task 4).

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

### Task 8: The documentation

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

### Task 9: The guard that keeps the word reserved

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

### Task 10: File the Fork issue

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

### Task 11: Make the convention explicit in the ESP, and file the validator

The expectation is inherited from the platform, so the platform should state it. The submodule has its own release path, so this is a separate PR plus an issue.

**Files:**
- Modify (submodule): `lib/event-sourcing-platform/docs-site/docs/event-store/concepts/ubiquitous-language.md`
- Produces: one submodule PR, one ESP issue.

- [ ] **Step 1: Add the note to the ESP vocabulary doc**

At the end of `lib/event-sourcing-platform/docs-site/docs/event-store/concepts/ubiquitous-language.md`:

```markdown
## Consuming systems own their own vocabularies

This document is the EVENT STORE's vocabulary. It is not the vocabulary of a
system built on it.

A bounded context is defined by the language spoken inside it, so every bounded
context in a consuming system owns a ubiquitous language file of its own,
covering that context's domain terms rather than these platform mechanisms.

**Recommended file naming:** `<bounded-context>-ubiquitous-language.md`, context
name first, so a search across a repository returns files whose names say which
context each one speaks for rather than N identically-named files.

A consuming system that cannot point at a vocabulary per context has folklore
where it should have an artifact. Syntropic137 enforces this with a QA check
(`ci/fitness/code_quality/test_ubiquitous_language.py`) that fails when a
context has no file, when a file names no context, or when a file outlives its
context. ESP should ship that check so consumers inherit it rather than
reinventing it - see the validator issue.
```

- [ ] **Step 2: Commit and push the submodule branch, open the PR**

```bash
cd lib/event-sourcing-platform
git checkout -b docs/consuming-systems-own-vocabularies
git add docs-site/docs/event-store/concepts/ubiquitous-language.md
git commit -m "docs(ubiquitous-language): consuming systems own a vocabulary per bounded context

This document is the event store's vocabulary, which consumers were reasonably
reading as the only one required. A bounded context is defined by the language
spoken inside it, so each one owns a file, and the naming standard puts the
context first so a search says which is which."
git push -u origin docs/consuming-systems-own-vocabularies
gh pr create --title "docs(ubiquitous-language): consuming systems own a vocabulary per bounded context" --body "<the rationale above, plus: syn137 found all five of its contexts had no vocabulary, and the missing convention is why>"
```

Do NOT bump the submodule pointer in syn137 as part of this plan. A docs-only submodule change does not need to reach a running workspace, and bumping the pointer drags an image build into a rename.

- [ ] **Step 3: File the validator issue on ESP**

```bash
gh issue create --repo syntropic137/event-sourcing-platform \
  --title "Ship a ubiquitous-language validator so consumers inherit the convention" \
  --body-file <path>
```

Body:

```markdown
A bounded context is defined by the language spoken inside it, so every context
in a consuming system should own a ubiquitous language file. ESP documents the
convention (see the vocabularies PR) but does not enforce it, so each consumer
reinvents the check or - as Syntropic137 did - simply lacks it.

Syntropic137 discovered on 2026-09-27 that ALL FIVE of its bounded contexts had
no vocabulary file, and the absence had already cost a domain word: one
operation was called both `fork` and `resume` until the meanings were separated,
and `fork` had to be reclaimed.

## What to ship

A validator consumers can run as a QA gate, parameterised over the contexts it
discovers rather than a hardcoded list:

- every bounded context directory has `<context>-ubiquitous-language.md`;
- every such file names its context near the top;
- no vocabulary file outlives the context it speaks for;
- the discovery itself is asserted non-empty, so a discovery bug cannot make the
  whole gate vacuous.

Syntropic137's working version is
`ci/fitness/code_quality/test_ubiquitous_language.py` and is the obvious
starting point - it is a plain pytest module with no syn137-specific imports
beyond the contexts path, which would become configuration.

## Why in ESP rather than per consumer

The expectation is inherited from ESP: consumers adopt bounded contexts because
ESP prescribes them. A convention ESP states but does not enforce is one every
consumer discovers the hard way.
```

- [ ] **Step 4: Cross-link**

Add the ESP issue reference to the `## Purpose` section of each syn137 vocabulary file and to the AGENTS.md section, so a reader knows the convention has a platform home. Commit.

---

## Appendix A: orchestration vocabulary

The full content for `docs/architecture/orchestration-ubiquitous-language.md`, referenced by Task 2 Step 1.

```markdown
# Ubiquitous Language: orchestration

## Purpose

The vocabulary of the `orchestration` bounded context. These words have exactly
these meanings in code, in the API, in the CLI and in conversation. Where a term
here disagrees with any other document, this one is canonical.

This is the DOMAIN vocabulary. For event-sourcing patterns - Event, Aggregate,
Projection, Processor - see `es-glossary.md`. For the event store's own terms see
`lib/event-sourcing-platform/docs-site/docs/event-store/concepts/ubiquitous-language.md`.
A term belongs here when it names something this system's users talk about, and
there when it names a mechanism the platform provides.

Every bounded context has one of these. See AGENTS.md, "Ubiquitous Language".

---

## Execution

One run of one Workflow, identified by an `exec-` id, recorded as an event
stream. An Execution is never rewritten: its history is the record of what
happened, including how it ended.

Statuses: `not_started`, `running`, `completed`, `failed`, `cancelled`,
`interrupted`. The last four are terminal. There is no paused state - see
"Words we do not use".

## Phase

One step of a Workflow inside an Execution, with its own agent, model, prompt
and timeout. Phases run in a total order given by `order`, which
`WorkflowDefinition.from_yaml` guarantees is unique per Workflow.

A Phase is completed only when the Execution recorded it so. A Phase that
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
including its terminal status, and records that it was resumed. One Resume per
Execution.

## Fork

Copying any Execution that has completed at least one Phase - INCLUDING a
`completed` one - into a new Execution that starts from a CHOSEN completed
Phase rather than from the first unfinished one.

Where Resume derives its starting point, a Fork is given one. Where Resume
carries the original configuration unchanged, a Fork exists in order to vary
something - a model, a prompt - against the same baseline.

**Not implemented.** The word is reserved so the capability can be built without
renaming anything. Until it ships, an operation that continues unfinished work
is a Resume and is called one.

## Inherited Phase

A Phase a resumed Execution does not re-run, because the Execution it came from
completed it. Carries the artifact ids that Phase produced, and the id of the
Execution that actually produced them - which may be an ancestor further up a
chain, not the immediate predecessor.

## Resume Phase

The Phase a resumed Execution starts at: the first Phase, in order, that the
original did not complete. Restarted from its beginning.

A Resume Phase that had already STARTED in the original may have pushed or
published something, and re-running it repeats that, so resuming such an
Execution requires the operator to acknowledge it.

## Pin

A fact an Execution records about itself at start so it can be reproduced
without consulting anything mutable: the full runnable configuration of every
Phase, and the commit each repository was at.

A Pin is why a resumed Execution runs what the original ran even if the Workflow
has been edited since.

## Admission

The decision that an operation may proceed, recorded before any work begins.
Resuming is admitted or refused against the original's recorded state; the new
Execution is then created and started by a background processor.

An admitted Resume is not a started one. The two are separate facts and a
successful API response reports the first.

## Words we do not use

- **Pause.** Deleted 2026-09-27. It recorded an event that nothing in the
  execution path observed, so a paused Execution kept running. Cancel is the
  mechanism that works. Pausing for real would require the processor to observe
  the status, which was never written.
- **Branch.** Reserved, no meaning assigned. If a chat-style "branch from here"
  operation is ever wanted, this is where it gets defined.
- **Retry.** A Phase attempt within one Execution (`PhaseRetryScheduled`), never
  a new Execution.
- **Fork, in the process sense.** `GRPC_ENABLE_FORK_SUPPORT` and `os.fork` are
  unrelated to this vocabulary. Renames must not touch them.
```

## Self-Review

**Spec coverage.** Decision 1 (full rename) is Tasks 5-8. Decision 2 (resume = unfinished) is Task 2's definition plus the unchanged `RESUMABLE_STATUSES`. Decision 3 (fork spec) is Task 10. Decision 4 (delete pause) is Task 4. Decision 5 (vocabulary per context, enforced) is Tasks 1-3. Decision 6 (naming standard) is Task 1's validator and Task 3's AGENTS.md entry. Decision 7 (ESP states it) is Task 11. No gaps.

**Placeholders.** The four non-orchestration vocabularies are the one place this plan does not hand over finished prose, deliberately: their terms must be read out of each context's aggregates rather than invented, so Task 2 Step 2 gives the file shape, the minimum term list per context, and an explicit instruction to mark a genuinely unclear term `**Unclear:**` instead of guessing. Everything else carries its content.

**Type consistency.** Task 4 removes `ResumeExecutionCommand` (old meaning) and its test asserts the absence; Task 5 reintroduces the name with the new meaning; Tasks 6-9 consume it under that name. `ResumeOrigin`, `ResumeStartRecord`, `refuse_resume_start`, `decide_resume` are introduced in Task 5 and used in 6, 7 and 9 exactly so. `ResumeResponse.source_execution_id` is named in Task 6's Interfaces and used in Task 7's output.

**Review Focus coverage.** Items 1 and 2 (legacy event shapes) are Task 5 Step 1. Item 3 (old fork path) is Task 6 Step 1. Item 4 has changed meaning now that pause is deleted rather than aliased: the risk is a caller of the deleted `POST /executions/{id}/pause` or `syn control resume`, and Task 4 Step 6 pins that the routes are gone from the spec, with the deletion called out as breaking in its commit. Item 5 (the word drifting back) is Task 9.

## Risks the executor must not smooth over

- **The rename is only free while no events exist.** Measured 2026-09-27: zero `ExecutionPaused`, zero `ExecutionResumed`, zero `ExecutionForked` in production of 26,917 total, and the fork route returns 404 on the deployment. Task 5's payload-shape discriminator is what protects a replay if any appear before this merges. Do not delete it as unnecessary.
- **Deleting pause is a breaking API and CLI change.** It is justified because the feature never functioned, not because nobody used it. Task 4 Step 1 re-confirms the premise before anything is removed and says to stop if a hit appears in the execution path.
- **`git mv` of `slices/start_fork` changes a slice path.** `vsa-validate` has opinions about slice structure; run it immediately after the renames in Task 5, not at the end.
- **The four non-orchestration vocabularies are written from code that this plan's author has not read.** Expect `**Unclear:**` entries and treat them as findings worth raising, not as failures of the task.
- **Do not bump the ESP submodule pointer.** Task 11 is docs-only in the submodule; bumping drags an image build into a rename.
