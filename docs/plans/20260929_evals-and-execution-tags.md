# Evals, execution tags, and pinned repository state

Status: proposed implementation plan. Date: 2026-09-29.

## Progress (updated 2026-10-05)

| Step | State | Where |
|---|---|---|
| Tags on workflows and executions (prerequisite) | merged | #1526, #1541 |
| 1. Typed contracts, 2. Eval aggregate | merged | #1539 |
| 3. Workflow/execution metadata (default eval, attach/detach) | merged | #1562 |
| 4. Pinned launch integration | part A in review (ref resolver, freeze, resolved eval context, frozen SHAs fed to checkout) | #1591 |
| 5. Projections and wiring | not started | |
| 6. API and CLI | not started | |
| 7. Dashboard and docs | not started | |
| 8. Integration acceptance | not started | |

Issue: #967. Keep this table current when a step's PR merges.

## Product goal

Create an eval with an ID, goal, optional starting workflow, and optional repository baseline. Run ordinary Syn137 workflows within it. Those runs remain visible in Executions, carry an Eval badge, and appear together on the eval page. Attach existing executions retroactively. Support ordinary tags on workflows and executions, including tags authored in workflow YAML.

This first release organizes experiments and preserves their inputs. Automated scoring and workflow promotion are later consumers of these records.

## Existing architecture inspected

The implementation must follow the current event sourcing setup:

- `AGENTS.md`, Event Sourcing Architecture: aggregate decisions, two event lanes, Processor To-Do List, replay boundaries, guarded in-memory adapters, and coordinator subscriptions.
- `packages/syn-domain/src/syn_domain/contexts/orchestration/domain/aggregate_skill_registration/SkillRegistrationAggregate.py`: `@aggregate`, `@command_handler`, `@event_sourcing_handler`, validation before `_apply`, and replayable state.
- `.../orchestration/slices/register_skill/RegisterSkillHandler.py`: repository ports, create-only persistence, and concurrent creation handling.
- `.../orchestration/slices/register_skill/slice.yaml` and `projection.py`: slice metadata and versioned `AutoDispatchProjection`.
- `packages/syn-adapters/src/syn_adapters/projections/manager_registry.py`: production projection construction.
- `packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_service.py`: current coordinator, checkpoint and replay path.
- `apps/syn-api/src/syn_api/_wiring.py`: repository, handler, and projection dependency wiring.
- `.../orchestration/domain/commands/ExecuteWorkflowCommand.py` and `slices/execute_workflow/ExecuteWorkflowHandler.py`: typed repository identities, execution IDs, admission tickets, and existing processor dispatch.
- `.../orchestration/domain/events/WorkflowExecutionStartedEvent.py`: durable execution start record. `phase_definitions` alone is not a complete workflow snapshot, but the event already carries optional `pinned_phases` (runnable phase configuration, #1454) and `source_commits`. Step 4 extends those; it must not add a competing snapshot path.
- `.../contexts/_shared/repository_ref.py`: repository identity only, with no revision field.

Important distinction: `manager_event_map.py` describes a deprecated dispatch path. Register new production projections with the coordinator setup; do not introduce direct projection dispatch or rely on the legacy event map as the delivery mechanism.

## Domain decisions

### Ownership

Add `EvalAggregate` to the existing `orchestration` context. Evals share workflow/execution language and use the existing orchestration machinery. A new domain concept does not require another bounded context or service.

The Eval aggregate owns its goal, default workflow, baseline repositories, tags, and archived state. Execution aggregates own execution tags and eval membership. Workflow aggregates own workflow tags and an optional default eval ID. This avoids appending every run to an ever-growing Eval stream and avoids two aggregate writes to attach one execution.

`EvalRun` is a read model derived from execution events, not a second execution engine or aggregate.

### Records

| Record | Fields |
|---|---|
| Eval | `eval_id`, `name`, `goal`, `starting_workflow_id?`, `baseline_repos[]`, `tags[]`, `archived`, timestamps |
| RepositoryBaseline | typed repository identity, `requested_ref`, `commit_sha` |
| Workflow metadata | `tags[]`, `default_eval_id?` |
| Execution eval membership | `eval_id?`, `association_kind` (`launched` or `attached`), association timestamp |
| Execution start snapshot | exact workflow definition + digest, effective inputs/task, repo baselines, inherited tags, eval goal at launch |
| Repository checkout observation | execution/phase/repo identity, expected SHA, observed SHA, observation timestamp |

Use typed immutable value objects and frozen Pydantic boundary models. Reuse `RepositoryRef` inside a new revision-bearing value object; do not overload its identity fields.

An execution belongs to at most one eval in v1. Duplicate attachment to the same eval is idempotent. Attaching to another requires an explicit detach first. Preserve original launch metadata even after detachment or reassignment.

### Tags and eval membership

Tags are ordinary labels, such as `refactor`, `baseline`, or `candidate`. Eval membership is a typed ID relationship. The UI derives its Eval badge from that relationship; a free-form tag named `eval` cannot establish membership.

Normalize tags by trimming, lowercasing, deduplicating, and sorting. Implemented limits (`_shared/tags.py`): 32 tags per record, 64 characters per tag, lowercase letters/digits plus `-`, `_`, `.`, `/` and `:`. These are product limits, not measured capacity claims.

Workflow YAML accepts `tags` and optional `default_eval_id`. Creation/import/update/export retain both fields. Existing workflows can be tagged through commands.

At launch, snapshot the union of workflow and request tags. Later workflow tag edits affect future runs. Execution tags can be edited retroactively without changing the original inherited-tag snapshot.

Eval resolution order: explicit eval selection, then workflow default. Support an explicit ordinary-run choice that suppresses the default. Evaluate membership at dispatch; changing a workflow default never reclassifies historical runs.

### Repository baseline

An eval may have zero or multiple repos. Accept a branch, tag, or commit as `requested_ref`; resolve it once to a full commit SHA before saving the baseline. Preserve the original ref for display. New runs use the saved SHA, even when the branch/tag moves.

Resolve git state through a typed infrastructure port and the existing repository/auth boundary. Aggregates validate resolved values and emit events; they do not call GitHub or git. API routes remain thin. Inspect ADR-066 and the current client/server git boundary before choosing the concrete resolver location.

Freeze the goal and baseline once the first run is admitted. Name and ordinary tags remain editable; changing the experiment goal or baseline creates another eval. Establish freezing through an aggregate command and persisted event before dispatch, so an eventual projection read cannot permit a concurrent baseline edit. A frozen eval with no successful runs remains valid and reusable.

For launched eval runs, baseline repos take precedence over workflow repo defaults. Reject conflicting explicit repo/ref overrides. An eval without repos can use a workflow's repositories, but dispatch must resolve and persist their exact starting SHAs. Reject repo-requiring workflows if their repo inputs cannot be established.

Extend the existing workspace provisioning contract so each repo checks out its own SHA. Verify the initial checkout before the first agent receives access. A mismatch fails setup. Subsequent phases preserve normal workflow changes; do not reset each phase to the baseline. Record the actual starting state through a domain command after provisioning.

Pinned commits recreate source state while those objects remain retrievable. Record existing image, model, skill and plugin identities when available; this feature does not promise identical model outputs or external service state. Git bundles and environment archival can be added later if retention becomes a requirement.

### Retroactive attachment

Attachment changes classification only. It does not rerun work or assert that the run used the eval baseline.

Keep the execution's original task, workflow snapshot and starting SHAs. Display whether its recorded repository state matches the eval baseline: `matches`, `differs`, or `unknown`. Missing historical state stays unknown. Never copy the eval baseline into a historical run as if it were observed.

Allow any terminal status, including failed/cancelled executions. Preserve `association_kind=attached` so reports can identify historical additions.

## Commands and events

| Owner | Commands | Events |
|---|---|---|
| Eval | CreateEval, UpdateEval, FreezeEval, ArchiveEval | EvalCreated, EvalUpdated, EvalFrozen, EvalArchived |
| Workflow | AddWorkflowTags, RemoveWorkflowTags, SetWorkflowDefaultEval | WorkflowTagsAdded, WorkflowTagsRemoved, WorkflowDefaultEvalSet |
| Execution | existing start command with optional eval/snapshot fields | WorkflowExecutionStarted with backward-compatible fields, or a new event version using the SDK's supported evolution convention |
| Execution | AttachExecutionToEval, DetachExecutionFromEval | ExecutionAttachedToEval, ExecutionDetachedFromEval |
| Execution | AddExecutionTags, RemoveExecutionTags | ExecutionTagsAdded, ExecutionTagsRemoved |
| Execution | RecordRepositoryCheckout | RepositoryCheckoutRecorded |

Use the project's event naming/decorator conventions. Each aggregate handler validates its own invariants. Application handlers validate referenced eval/workflow existence by loading authoritative aggregates, never by treating a lagging projection as authoritative.

Creating a stream uses the repository's create-only expected version. Updates use optimistic concurrency. Add/remove operations are idempotent; avoid replace-all tag commands that lose concurrent additions.

Archived evals remain readable and keep runs. New launches and attachments are refused after archival admission checks; already admitted runs continue. Detachment and tag corrections remain allowed. Document the admission linearization point, following existing admission-ticket semantics.

## Launch and recovery

1. Resolve eval selection and load current authoritative eval/workflow state.
2. Validate inputs, repo access, and exact SHA availability through existing admission boundaries.
3. Freeze the eval with optimistic concurrency; reload/revalidate if an update wins the race.
4. Build the immutable effective workflow/input/repo snapshot and select the existing execution ID.
5. Pass typed eval context through `ExecuteWorkflowCommand`, handler, processor, and aggregate start command. Persist membership and snapshots in the execution start record before work starts.
6. Use the existing Processor To-Do List for provisioning, execution, and recovery. Provision the first workspace from the pinned baseline and record verified checkout state.
7. Coordinator subscriptions build eval and execution read models, then update the existing realtime/UI path.

Do not create a separate eval dispatch loop. If durable preparation beyond the existing admission/start path is needed, use a ProcessManager with persisted pending work and stable execution IDs. Projection handlers remain pure during replay. A restart must never launch an extra eval run.

Command responses return authoritative IDs/state without waiting for projections. Clients handle the existing eventual-consistency contract. Preserve the maintenance admission ticket until the durable execution start, as current dispatch does.

## Read models and interfaces

Add versioned `EvalListProjection`, `EvalDetailProjection`, and `EvalRunsProjection` under owning slices. Extend workflow and execution list/detail projections for tags/default eval/membership. Membership rows use execution ID as identity; replayed events cannot duplicate a row or inflate counts.

Keep execution status, cost, duration and artifacts in their existing read models. Eval run queries join those facts; preserve unknown duration and unpriced cost indicators. Avoid duplicating an alternative cost calculator.

Proposed API surface under the current `/api/v1` prefix:

- `POST /evals`, `GET /evals`, `GET /evals/{id}`, `PATCH /evals/{id}`, `POST /evals/{id}/archive`.
- `POST /evals/{id}/runs`: select a workflow or use the starting workflow; dispatch via existing execution admission.
- `GET /evals/{id}/runs`: paginated execution-backed rows.
- Attach/detach membership and add/remove tags through explicit command endpoints, following existing route conventions.
- Existing execution lists gain `eval_id`, `is_eval`, and tag filters. Workflow lists gain tag filters.
- Existing workflow-run requests accept an optional eval selector and explicit default suppression.

All endpoints use typed request/response models. Run `just codegen`; consume generated types in the Node CLI. Suggested commands: `syn eval create/list/show/run/attach/detach/archive`, plus workflow/execution tag commands. Final command spelling follows existing CLI conventions.

Dashboard: Evals list, create form, detail with goal/baseline/run table, and Run workflow action. Execution list/detail shows clickable Eval badge, tags, and filters. Historical attachments show Attached; repo matching is visible on eval run rows. Workflow forms and YAML support tags/default eval. A baseline mismatch never silently becomes a matched run.

## Implementation sequence

| Step | Depends on | Deliverable and acceptance |
|---|---|---|
| 1. Typed contracts | none | Value objects, commands/events, evolution fixtures, and explicit default/tag semantics |
| 2. Eval aggregate | 1 | Create/update/freeze/archive, repository adapter, replay and concurrency tests |
| 3. Workflow/execution metadata | 1, 2 | YAML retention, tag events, default eval, retrospective attach/detach; old events replay unchanged |
| 4. Pinned launch integration | 2, 3 | Snapshots flow through existing admission/processor/provisioning; multi-repo checkout verified; restart preserves membership |
| 5. Projections and wiring | 2, 3, 4 | Registry/coordinator/store setup, slice manifests, pagination/filter support; replay produces identical read state without dispatch |
| 6. API and CLI | 4, 5 | Typed endpoints, codegen, thin route/client behavior, command receipts under projection lag |
| 7. Dashboard and docs | 6 | Create/run/attach/filter flows; clear baseline and historical-state display |
| 8. Integration acceptance | 7 | End-to-end scenario and required repository QA pass |

Extend the existing Python domain/API and TypeScript clients. This is integration with established infrastructure; a separate Rust implementation would introduce another service and competing persistence pattern. Use `uv run` for Python tools/tests.

## Required verification

- Create an eval with a goal, optional workflow, and two repos at different SHAs; replay reconstructs it exactly.
- Launch two workflows under that eval; both appear in Executions and eval runs with correct links and unchanged pinned inputs.
- Move a baseline branch/tag after creation; future runs still start from the stored SHA.
- Verify actual multi-repo checkout before agent execution; missing SHA or mismatch fails visibly.
- Change a workflow after one run; the first run retains its definition and the next captures the new definition.
- Add workflow tags, launch, then edit workflow tags; historical inherited tags remain stable and execution tags stay editable.
- Explicit eval overrides default; ordinary-run selection suppresses default; tag named `eval` has no membership effect.
- Attach a failed historical run with unknown starting state; show Attached and unknown, with no fabricated snapshot.
- Duplicate attachments/tag additions and repeated event delivery are idempotent; conflicting membership commands are rejected or retried under optimistic concurrency.
- Freeze versus update and archive versus launch races obey defined admission semantics.
- Restart/replay reconstructs membership, tags, and snapshots without launching work or calling git.
- Old workflow/execution events still deserialize/replay; unrelated ordinary dispatch behavior stays compatible.
- Projection wiring tests cover coordinator delivery, persistence, rebuild and checkpoint recovery. Codegen and API drift checks pass.

Run focused domain/adapter/API/CLI/UI tests for changed behavior, then the required preflight and relevant CI-equivalent gates listed in `AGENTS.md`. No paid agent run is needed for deterministic integration acceptance; use the established execution/provisioning test doubles. A live eval smoke run is a later operational check.

## Completion criterion

An operator can create an eval, select a starting workflow and pinned repo baseline, launch or attach executions, find/filter those runs in the ordinary execution UI, and inspect what source/workflow each run actually started with. Event replay restores the same records through the existing coordinator without starting new work.
