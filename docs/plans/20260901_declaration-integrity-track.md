# Declaration integrity track

**Goal.** A workflow phase declares what it needs, and the platform either
honours the declaration or refuses it. Nothing is validated, stored, and then
quietly dropped.

Everything below follows from one finding: `ExecutablePhase` has a single
production construction site (`ExecuteWorkflowHandler.py:347-361`), and four
authored fields never reach it.

## Order, and why

### 1. #1039 widened: wire the dropped fields

`input_artifacts`, `allowed_tools`, `execution_type`, `argument_hint` are
validated, persisted, projected, re-exported as YAML, and never applied.

This is first because it is the difference between a phase definition being a
document and being a configuration. Per-phase tool scoping does nothing today.
Artifact injection is unconditional, so every phase carries every earlier
phase's output whether its job needs it or not. Both of the knobs that would
make a phase narrow are the two that are dropped.

**Not a uniform change.** The four fields differ sharply in risk:

- `allowed_tools`: mechanical. The emit path exists (`_wiring.py:309`), the
  vocabulary validator exists (#964), the codex refusal exists but is
  unreachable. Wiring it makes all three live.
- `argument_hint`: cosmetic, and possibly should be deleted instead. It is
  slash-command heritage, and the command surface is gone.
- `input_artifacts`: a behaviour change with blast radius. Today every phase
  receives every completed phase's output. Honouring the declaration means some
  phases stop receiving artifacts they currently get. Existing workflows were
  authored against the actual behaviour, not the declared one.
- `execution_type`: cannot be honoured at all today. `parallel` has no
  implementation. Wiring it without one converts a silent lie into a crash.

So the deliverable is not "wire four fields". It is a decision per field:
apply it, refuse it, or remove it. See ADR-069 D5.

### 2. #967: tag executions

Group and compare runs. Without it, comparing one workflow version to the next
is manual artifact diffing. This is the minimum viable evaluation primitive and
the gate on any measured iteration.

### 3. #1034: record real operations

`RecordOperationHandler.handle()` is a comment. One synthetic totals-only
operation is written per session, so a session's operation list is a roll-up
wearing the shape of a history.

Consequence, observed: an audit of whether a verify phase checked out the
correct commit could not be answered from the platform's own records. The tool
timeline shows that a `checkout` happened and not what it checked out. The only
evidence available was the agent's own prose, which is the class of evidence
this track exists to stop relying on.

### 4. Then: measured workflow iteration

With 1 through 3 landed, a workflow version can be compared to the one before
it on evidence the platform produced rather than on the agent's narration.

## Explicitly not in this track

- **Recipe standard adoption.** Tracked separately. Its first consumer should be
  the marketplace validator, which is what makes it load-bearing rather than
  aspirational. Blocked upstream on a Python loader (APSS #127).
- **MCP per phase.** After the format settles.
- **The tiering rule from ADR-069.** Belongs upstream in the standard, not in a
  private layer here.

## Open questions this track must answer

1. For `input_artifacts`: is the fix to honour the declaration, or to delete the
   field and document that all prior outputs are always injected? Honouring it
   is better for context efficiency and worse for compatibility. How many
   installed workflows would change behaviour?
2. For `execution_type`: refuse `parallel` at authoring time until a parallel
   processor exists, or build one? Refusing is honest and cheap; building it is
   what the experimentation fan-out eventually needs.
3. For `argument_hint`: delete, or keep? It has no consumer.
4. Does any installed workflow currently depend on receiving artifacts it does
   not declare? This is answerable by measurement against the deployment, and it
   decides question 1.
