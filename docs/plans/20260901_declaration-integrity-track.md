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
- `input_artifacts`: CANNOT be honoured as written. Corrected 2026-09-01 after
  measurement by syntropic137-f1; the framing above this line was wrong and is
  kept only in the open questions below as a record of the error. Injection is
  keyed by PHASE ID (`_wiring.py:497`, `:509` both iterate `phase_outputs`
  keyed by `pid`), while the declaration is keyed by ARTIFACT TYPE
  (`workflow_definition.py:414` maps `input_artifacts` to
  `input_artifact_types`). Across all 22 authored multi-phase workflows the
  intersection of the two vocabularies is EMPTY. Filtering a phase-id-keyed
  dict by a set of type names would therefore deliver nothing to every phase.
  This is not a blast radius to size; it is guaranteed total breakage.

  The useful finding underneath: authors use the field coherently as a
  type-level dependency graph. 31 of 33 declarations resolve to a prior phase's
  declared output type. It is a meaningful assertion wired to nothing.
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

1. ANSWERED 2026-09-01, and the question as posed was malformed. It assumed the
   filter was expressible. It is not, for the reason recorded above. The
   decision is REFUSE: validate at workflow creation that every declared input
   type is produced by a prior phase's `output_artifacts` or by a workflow-level
   input, and reject otherwise. Zero runtime change, no compatibility risk, and
   the field stops being inert by becoming a checked assertion.

   THE QUESTION THIS PRODUCES, which is now the live one: making
   `input_artifacts` a checked assertion does not make phases context-efficient.
   Every phase still receives every prior phase's output. Narrowing requires a
   PHASE-ID-KEYED field, since that is the channel that exists, something like
   `inputs_from: [phase-id]`. That is a deliberate design decision touching
   ADR-069, not a retrofit onto the type graph, and it needs the owner.
2. For `execution_type`: refuse `parallel` at authoring time until a parallel
   processor exists, or build one? Refusing is honest and cheap; building it is
   what the experimentation fan-out eventually needs.
3. For `argument_hint`: delete, or keep? It has no consumer.
4. Does any installed workflow currently depend on receiving artifacts it does
   not declare? This is answerable by measurement against the deployment, and it
   decides question 1.
