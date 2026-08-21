# Execution isolation for the background dispatcher (#865)

Status: design, not implemented. No production code changes accompany this document.

Baseline: `origin/main` at `b7dbf1c6`. Every line number below is against that commit.
Every measurement below was taken in a detached worktree of that commit with
`APP_ENVIRONMENT=test`.

Related: #861 (ordered teardown / spool backfill), #866 (the merged mitigation),
#867 (durable queued/running states).

---

## 1. Root cause in one sentence

`BackgroundWorkflowDispatcher` builds ONE `WorkflowExecutionProcessor` at startup
(`apps/syn-api/src/syn_api/services/lifecycle.py:469` -> `_wiring.py:868-874` ->
`_wiring.py:838-865` -> `_wiring.py:141`) and runs up to `max_concurrent`
executions through it concurrently, while that processor keeps twelve pieces of
mutable per-execution state on the instance.

The manual API path does not share: `apps/syn-api/src/syn_api/routes/executions/commands.py:381`
calls `get_execute_workflow_handler()` per request, which calls
`get_execution_processor()` per request, which returns a new object every call.
That is why manual executions never reproduced any of these defects despite
bypassing the semaphore entirely.

### The shared state

`packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/WorkflowExecutionProcessor.py`

| Attribute | Declared | Keyed by |
|---|---|---|
| `_inputs` | never declared; assigned at `:214` inside `run()` | nothing - a single value |
| `_active_workspaces` | `:173` | `phase_id` |
| `_active_prompts` | `:176` | `phase_id` |
| `_active_workspace_cms` | `:177` | `phase_id` |
| `_active_envs` | `:178` | `phase_id` |
| `_active_cmds` | `:179` | `phase_id` |
| `_session_managers` | `:180` | `phase_id` |
| `_phase_session_ids` | `:182` | `phase_id` |
| `_phase_tokens` | `:183` | `phase_id` |
| `_phase_auth_tokens` | `:184` | `phase_id` |
| `_phase_artifact_ids` | `:187` | `phase_id` |
| `_phase_started_at` | `:188` | `phase_id` |
| `_shared_workspaces` | `:192` | **`execution_id`** - already correct |

`phase_id` comes from the stored workflow definition
(`ExecutablePhase.phase_id`, threaded through `TodoItem.phase_id`), so it is
stable across runs of the same workflow. Two concurrent runs of one workflow
collide on every row above except the last.

`_shared_workspaces` and `_cleanup_shared_workspace(execution_id)` (`:534-543`)
are correctly execution-scoped. Nothing in this design changes them.

---

## 2. The three defects, with evidence

I re-derived all three against `b7dbf1c6` rather than taking the issue thread on
trust. Reproduction script: `/tmp/repro865_verify.py` (not committed; it becomes
the regression tests in §7).

### Defect 1 - crossed `self._inputs`. Silent wrong results.

`run()` writes the per-execution inputs onto the shared instance:

```
:212  if repos and "repos" not in inputs:
:213      inputs["repos"] = ",".join(r.https_url for r in repos)
:214      self._inputs = inputs
```

and `_provision_or_reuse_workspace()` reads it back, twice, while provisioning
a phase - long after another execution may have overwritten it:

```
:650              inputs=self._inputs,     # shared-workspace follow-up path
:667          inputs=self._inputs,         # normal provision path
```

`inputs` reaches `PromptBuilder`, including `inputs["repos"]` written at `:213`
from the typed `RepositoryRef` list (ADR-063), so the crossed values reach the
agent's prompt and its repo set.

Observed:

```
A started with: {'target': 'customer-A', 'repos': 'github.com/acme/a'}
A now reads   : {'target': 'customer-B', 'repos': 'github.com/acme/b'}
VERDICT A provisions with B's inputs: True
```

This is the worst of the three. It needs no cancellation and no id collision -
only two concurrent executions - and it fails silently: the workflow *completes*,
against the wrong target, and nothing downstream can tell.

Secondary observation: `_inputs` is not declared in `__init__` at all
(`hasattr(processor, "_inputs")` is `False` on a freshly built processor -
measured). Any path that reached `:650`/`:667` without `run()` having assigned it
would `AttributeError`. Today `run()` always assigns first, so this is a latent
typing/robustness gap rather than a live bug, but it is why pyright does not see
a type for it.

### Defect 2 - unscoped teardown. One execution's exit destroys others' containers.

`_close_phase_workspace_cms()` (`:502-532`) iterates **every** entry in
`_active_workspace_cms` with no owner filter, probes and closes each, then
globally clears two dicts:

```
:511      shared_cms = {id(cm) for _, cm in self._shared_workspaces.values()}
:512      for _pid, workspace_cm in list(self._active_workspace_cms.items()):
:513          if id(workspace_cm) in shared_cms:
:516              continue
:521          await capture_phase_session(... self._active_workspaces.get(_pid) ...)
:528          await workspace_cm.__aexit__(None, None, None)
:531      self._active_workspace_cms.clear()
:532      self._phase_session_ids.clear()
```

It is called on the cancel path (`:394`) and the failure path (`:471`) of ONE
execution, both of which then also clear four more dicts wholesale
(`:395-398` and `:472-475`).

Observed, two executions of *different* workflows with no shared phase id, only
A cancelled:

```
A.closed = True   B.closed = True
session_ids after = []
VERDICT B torn down by A's cancel: True
```

So a running agent in an unrelated execution has its container destroyed, and its
session identity is wiped so the capture cannot be attributed.

Note the shape: re-keying by `(execution_id, phase_id)` does **not** fix this.
The loop would still walk every key. The iteration itself has to be scoped.

### Defect 3 - `phase_id`-only keys. Same-workflow concurrent runs overwrite each other.

`_handle_provision()` writes six rows keyed by `todo.phase_id` alone:

```
:594      self._session_managers[todo.phase_id] = session_mgr
:595      self._phase_started_at[todo.phase_id] = datetime.now(UTC)
:608      self._active_workspaces[todo.phase_id] = result.workspace
:609      self._active_workspace_cms[todo.phase_id] = result.workspace_cm
:610      self._active_envs[todo.phase_id] = result.agent_env
:611      self._active_cmds[todo.phase_id] = result.claude_cmd
:612      self._active_prompts[todo.phase_id] = result.interactive_prompt
```

and `_handle_run_agent()` reads them straight back (`:710-715`), as do
`_handle_collect_artifacts()` (`:810`), `_handle_complete_phase()` (`:857-860`)
and `_finalize_phase()` (`:932-953`). Two concurrent executions of the same
workflow reach the same key, and the later `_handle_provision` overwrites the
earlier execution's workspace handle and context manager before the earlier one
has finished with it - so the earlier execution runs its agent in the later
execution's container, and the orphaned context manager is never exited.

Not separately reproduced here; it follows directly from the key being
`phase_id` and `phase_id` being a property of the stored workflow. I have not
constructed a live two-execution run to observe it, and say so rather than
claiming a reproduction I did not perform.

### What is already correct

`_DispatchContext` (`:104-117`, created at `:244`) exists precisely because
someone hit this class of bug before (issue "D3", stress 2026-06-10) and moved
`current_phase_id` off the instance onto a per-run object. Its docstring names the
sharing explicitly. That is a partial, one-field precedent for Option B - it fixed
one field and left twelve.

---

## 3. Current mitigation (merged, #866)

`packages/syn-shared/src/syn_shared/settings/polling.py:111-129` sets
`max_concurrent_dispatches` default to `1`, and
`_wiring.py:761-770` makes the dispatcher's own default `1` so a caller who omits
the argument cannot reintroduce `5`.
`apps/syn-api/src/syn_api/services/lifecycle.py:206`/`:290` warns at startup when
the configured value is above 1.
`apps/syn-api/tests/test_execution_concurrency_posture.py` locks all of that in.

At concurrency 1 none of the three defects can fire from the dispatcher. The
manual API path is unbounded but unaffected, because it does not share a
processor. The purpose of this design is to make the default safe to raise again.

---

## 4. The options

### Option A - build handler + processor per execution in the dispatcher

Change `BackgroundWorkflowDispatcher` to hold a *factory* rather than an
instance, and call it inside the semaphore, once per execution. The processor's
dictionaries stay keyed by `phase_id`, because each processor then serves exactly
one execution.

**Correctness.** Fixes all three, by construction:

- Defect 1: `self._inputs` is written and read on an object no other execution holds.
- Defect 2: every entry `_close_phase_workspace_cms` iterates belongs to this
  execution, so "iterate everything" and "iterate mine" are the same set.
- Defect 3: `phase_id` is unique within one execution's phase list, so
  `phase_id`-keyed dicts are unambiguous.

Demonstrated: two processors, deliberately given the SAME `phase_id`, one
cancelled:

```
A.closed = True   B.closed = False
A inputs intact: {'target': 'customer-A'}   B inputs intact: {'target': 'customer-B'}
```

**Blast radius.** Small and confined to the composition root. The processor is
not touched. `apps/syn-api/src/syn_api/_wiring.py` around `:761-796` and
`:868-874`; two constructions in
`apps/syn-api/tests/test_execution_concurrency_posture.py:53,80`.

**Cost.** Measured on `b7dbf1c6`, `APP_ENVIRONMENT=test`, against the local dev
Postgres and MinIO:

```
first processor build          : 295.8 ms   (one-time: module imports + MinIO bucket check)
subsequent processor build     :   0.508 ms each  (n=50)
full ExecuteWorkflowHandler    :   0.560 ms each  (n=50)
```

0.56 ms against a workflow execution measured in minutes is not a cost. The
one-time 296 ms is already paid at startup today by the dispatcher's own
construction, and separately by the first manual execute.

Why it is that cheap - each verified by identity check in the same run:

| Collaborator | Shared? | Where |
|---|---|---|
| `get_event_store()` | singleton | `packages/syn-adapters/src/syn_adapters/events/store_helpers.py:79-116` |
| `AgentEventStore.initialize()` | idempotent, returns immediately when `_initialized` | `packages/syn-adapters/src/syn_adapters/events/store.py:80-95` |
| `get_artifact_storage()` | **cached** - delegates to `@lru_cache _get_artifact_storage_instance` | `packages/syn-adapters/src/syn_adapters/storage/artifact_storage/factory.py:27,86` |
| `get_conversation_storage()` | module singleton (and it *is* the one that does startup I/O) | `packages/syn-adapters/src/syn_adapters/conversations/minio.py:273-285` |
| `get_projection_manager()` | `@lru_cache` | `packages/syn-adapters/src/syn_adapters/projections/manager.py:270-274` |
| execution / session / artifact repositories | module singletons | `packages/syn-adapters/src/syn_adapters/storage/repositories.py:161-215` |
| `get_controller()` | singleton | `apps/syn-api/src/syn_api/_wiring.py:697-746` |
| plugin / skill resolvers + materializers | singletons | `_wiring.py:1216-1250, 1340-1369` |
| `WorkspaceService.create(...)` | **fresh per call, already today** | `_wiring.py:217-220` |
| `ExecutionTodoProjection(store=...)` | **fresh per call, already today**; the *store* is shared | `_wiring.py:229` |

Correction to the issue thread: an earlier comment stated that
`get_artifact_storage()` "constructs a fresh `MinioArtifactStorage` every call".
It does not on current main - `_get_artifact_storage_instance` carries
`@lru_cache` (factory.py:27) and `reset_artifact_storage()` calls `.cache_clear()`
on it (factory.py:105). Verified by identity: `a is b` -> `True`. The follow-up
comment retracting the concern reached the right conclusion for a slightly wrong
reason; there is no per-execution MinIO client and no per-execution connection
pool at all.

`WorkspaceService.create()` builds an `AgenticIsolationAdapter` and a
`WorkspaceDockerProvider`, both of which only assign attributes
(`packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py:101-134`;
`lib/agentic-primitives/lib/python/agentic_isolation/agentic_isolation/providers/docker.py:86-101`).
No Docker client, no socket. That is included in the 0.508 ms.

**`_shared_workspaces`.** Unchanged and still correct. It is keyed by
`execution_id`; with one execution per processor the dict simply holds at most one
entry. `_cleanup_shared_workspace(execution_id)` (`:534-543`) keeps working
verbatim, and the `id(cm)`-identity skip at `:511-516` keeps working because both
dicts live on the same instance as before.

**Cancellation.** Still reaches a running execution. `get_controller()` is a
process singleton (`_wiring.py:697-746`) that the processor merely *receives*
(`_wiring.py:226`); every one of its methods takes `execution_id`
(`packages/syn-adapters/src/syn_adapters/control/controller.py:126,178,185,192,196`)
and the signal queue is Redis-keyed by `execution_id`
(`packages/syn-adapters/src/syn_adapters/control/ports.py:31-39`). Cancellation has
never depended on processor identity.

**Restart / crash.** Unchanged. Nothing durable is keyed to a processor instance.
Orphaned containers are reaped at startup by Docker label and name prefix, not
from any in-process registry
(`apps/syn-api/src/syn_api/services/reconciliation.py:30-38`:
`label=syn.component=sidecar`, `name=agentic-ws-`). One consequence worth naming:
under Option A each execution gets its own `AgenticIsolationAdapter._workspaces`
dict (adapter.py:134), which is an isolation improvement, and it is not a
recovery regression because recovery never read that dict.

**Testability.** The regression tests do not depend on how the processor is built,
so they are written against the processor and stay valid either way. The new
dispatcher test is a straightforward "two dispatches, two distinct processor
objects" assertion on a factory call count.

**Interaction with #861.** #861 puts an archive-then-confirm-then-stop sequence
inside `_close_phase_workspace_cms`. Under Option A everything that loop iterates
belongs to one execution, so the manifest rows (execution id, workspace id, object
key, content hash) are correctly attributed for free, and the loop cannot archive a
workspace whose agent is still running in a *different* execution. #865 must land
first; otherwise #861 turns a transient mis-teardown into a durable
mis-attribution that then needs repairing.

**Interaction with #867.** Complementary, and Option A makes #867 easier. #867
wants a durable `queued`/`running` row that a drainer claims and executes.
"Construct the worker when you claim the item" is exactly Option A's shape;
"one long-lived worker shared by the drainer" is Option B's. Option A does not
fix #867 and is not blocked by it. Raising concurrency after #865 lands *shrinks*
#867's window (fewer items sit queued) without closing it.

**Residual risk.** `_close_phase_workspace_cms` still has no explicit owner
filter. It is correct only because of an invariant enforced elsewhere (one
execution per processor). If a future change reintroduces sharing, all three
defects come back silently. §5 addresses exactly this.

### Option B - per-run context object threaded through the processor

Move the twelve pieces of state onto a `@dataclass ExecutionRunState` created in
`run()` and threaded through `_drain_todo_list`, `_dispatch`, the four
`_handle_*` methods, `_finalize_phase`, `_close_phase_workspace_cms`,
`_cancel_execution`, `_fail_execution` and `_provision_or_reuse_workspace`.

**Correctness.** Fixes all three *if done completely*. Defect 1 is fixed by moving
`_inputs` onto the context. Defect 2 is fixed because the context's
`active_workspace_cms` only ever contains this run's entries. Defect 3 is fixed
because the dict is per-run, so `phase_id` is again unique within it - note that
re-keying to `(execution_id, phase_id)` is *not* what fixes it and is not needed.

The "if done completely" is the risk: a single missed `self._` reference among the
65 lines that touch this state leaves a silent cross-execution channel with no
test that would notice.

**Blast radius.** Large and in the highest-risk file. 12 attributes, 65 lines
referencing them, and 11 methods needing signature changes, all inside the
1024-line `WorkflowExecutionProcessor`. Measured by grep on `b7dbf1c6`.

**`_shared_workspaces`.** This is the one place Option B is *worse*.
`_shared_workspaces` is deliberately execution-scoped and shared across phases;
moving it onto a per-run context is a semantic no-op today (one run = one
execution_id) but changes the `shared_cms` identity check at `:511` and the
`is_shared` check at `:953` from "any execution's shared cm" to "this run's shared
cm". That is the intended behaviour, but it is a behaviour change to the
multi-agent interactive-tmux path that Option A does not make at all. Higher
regression risk on the least-tested backend.

**Cancellation.** Unaffected - same reasoning as Option A, the controller is a
singleton taking `execution_id`.

**Restart / crash.** Unaffected.

**Testability.** Better in one narrow respect: the per-run state becomes an
explicit, typed, injectable object you can assert on directly, rather than
private instance dicts. This is a real benefit and the main argument for B.

**Interaction with #861.** Also works: the archive loop reads
`ctx.active_workspace_cms`. No advantage over Option A.

**Interaction with #867.** Neutral to slightly negative - a long-lived shared
processor is the thing #867's drainer would have to keep correct.

**The cost/benefit.** Option B pays a large, high-risk refactor of the core
execution file to buy an isolation property that Option A gets for free from
object lifetime. The one thing it buys that A does not is *robustness against a
future caller sharing the processor deliberately* - and §5 buys that for about
ten lines.

### Option C (rejected) - scope only the cleanup iteration, plus re-keying

Give `_close_phase_workspace_cms` an `execution_id` parameter, filter the loop,
and re-key the eight/eleven dicts to `(execution_id, phase_id)`.

Rejected: it does not fix defect 1. `self._inputs` is a single value, not a dict;
there is no key to add. This is the option the issue thread walked into and then
out of, and it is the wrong one for exactly that reason - it fixes the loud
defects and leaves the silent one.

### Option D (rejected) - `contextvars`

Hold the per-execution state in `contextvars.ContextVar`s. Each `run()` is already
its own `asyncio.Task`, so the values would propagate correctly and no signatures
would change.

Rejected: it replaces an explicit shared object with an implicit ambient one.
Nothing in the type system or the signatures records that the state is
execution-scoped; a future helper called from the wrong task gets the wrong
values, or `LookupError`, with no compile-time signal. It also fights the
codebase's stated typing posture (ADR-032, "no string-keyed lookups when attribute
access is possible"). The debugging cost of ambient state exceeds what it saves,
and it makes #861's manifest attribution harder to reason about, not easier.

---

## 5. Recommendation: Option A, plus a re-entrancy guard

**Build the handler and processor per execution in the dispatcher (Option A), and
add a re-entrancy guard to `WorkflowExecutionProcessor.run()` that raises if a
second execution enters an instance that is already running one.**

Option A is the fix: it is a change to the composition root rather than to the
1024-line execution file, it fixes all three defects by construction rather than
by 65 careful edits, it is a pattern already proven in this codebase (the manual
API path has always done it), and it costs 0.56 ms per execution - measured, not
estimated.

The guard is what turns "correct because of an invariant held somewhere else"
into "correct because the object refuses to be misused". It converts every one of
these three defects, for any future caller, from silent corruption into a loud
crash at the moment of sharing. That is the property Option B was really being
bought for, at roughly ten lines instead of a full refactor of the file.

Do **not** re-key the dictionaries. Once one processor serves one execution,
`phase_id` is unique within it, and `(execution_id, phase_id)` keys would be 11
dicts of ceremony encoding an invariant the guard already enforces.

---

## 6. Implementation steps

Each step is independently reviewable. Steps 1-3 are the fix; step 4 is the
poka-yoke; step 5 is the restore.

**Step 1 - declare and type `_inputs`.**
`WorkflowExecutionProcessor.__init__` (`:172-194`): add
`self._inputs: dict[str, Any] = {}` beside the other per-execution state, with a
comment saying it is per-execution and therefore why the instance serves one
execution. Today it is an undeclared attribute assigned only at `:214`, invisible
to pyright. No behaviour change.

**Step 2 - re-entrancy guard on `run()`.**
Add `self._running_execution_id: str | None = None` in `__init__`, and at the top
of `run()` (before `:207`):

```python
if self._running_execution_id is not None:
    raise ProcessorAlreadyRunningError(self._running_execution_id, execution_id)
self._running_execution_id = execution_id
```

cleared in a `finally` around the existing `try` at `:246-294`. New exception type
beside the other orchestration errors. The docstring must state the invariant
plainly: *one processor serves one execution; the state at `:172-194` is
per-execution and the teardown at `:502-532` is unfiltered, so sharing an instance
crosses inputs and destroys other executions' containers (#865).*

This step is deliberately taken **before** step 3, so that a mistake in step 3
fails loudly in tests rather than silently in production.

**Step 3 - dispatcher builds per execution.**
`apps/syn-api/src/syn_api/_wiring.py`:

- `BackgroundWorkflowDispatcher.__init__` (`:761`) takes
  `handler_factory: Callable[[], Awaitable[ExecuteWorkflowHandler]]` in place of
  `handler: ExecuteWorkflowHandler`. Replace the parameter rather than adding an
  optional one: leaving an instance-accepting path is leaving the defect
  reachable.
- `_run()` (`:798-829`) awaits `handler = await self._handler_factory()` as its
  first statement inside the semaphore, before constructing the command, and uses
  that local instead of `self._handler` at `:819`.
  Construct **inside** the semaphore, not in `run_workflow()`: a queued execution
  should not hold a processor (and its `WorkspaceService`) while it waits.
- Factory failure is an execution failure, not a dispatcher failure: the existing
  `except Exception` at `:825-829` already covers it since the await is inside the
  `try`. Verify the ordering when implementing.
- `get_workflow_dispatcher()` (`:868-874`) passes the function
  `get_execute_workflow_handler` itself as the factory. It already returns a fresh
  handler and a fresh processor on every call (verified: `p is not p2` -> `True`);
  no change to `get_execute_workflow_handler` or `get_execution_processor` is
  needed.
- Update the two test constructions at
  `apps/syn-api/tests/test_execution_concurrency_posture.py:53,80` to pass a
  factory. `test_the_second_execution_waits_for_the_first` keeps working and
  keeps its meaning.

**Step 4 - keep the composition root honest.**
`_wiring.py:838-865` (`get_execute_workflow_handler`) is documented as the single
composition root for both paths. Its docstring gains a line: it returns a
handler+processor intended for exactly one execution, and callers must not cache
it. Nothing caches it today; this prevents someone "optimising" it into a
singleton later, which would silently restore all three defects.

**Step 5 - restore concurrency (see §8).**

Non-goals, stated so a reviewer can check they were not done:

- No re-keying of the eleven `phase_id`-keyed dicts.
- No change to `_shared_workspaces` or `_cleanup_shared_workspace`.
- No change to `_close_phase_workspace_cms`'s loop (#861 will change its body;
  #865 does not need to).
- No caching of `get_artifact_storage()` - it is already cached.

---

## 7. Test plan

### 7.1 Regression tests from the reproductions (required)

Both #865 reproductions become permanent tests. They are written against
`WorkflowExecutionProcessor` and are independent of how the processor is built, so
they hold under Option A, Option B, or any future rework. Home:
`packages/syn-domain/tests/contexts/workflows/execute_workflow/test_865_execution_isolation.py`,
following the existing `test_661_regression.py` naming, and building the processor
the way `test_processor_smoke.py:125-140` does (in-memory repos, MEMORY workspace
backend, `InMemoryProjectionStore`, `APP_ENVIRONMENT=test`).

1. **`test_one_executions_cancel_does_not_close_anothers_workspace`** (defect 2).
   Two processors, each with a recording context manager registered under the
   *same* `phase_id` - the hardest case, since it also covers defect 3. Cancel A.
   Assert `a_cm.closed is True` and `b_cm.closed is False`, and that B's
   `_phase_session_ids` still holds its session id. Against `b7dbf1c6` with a
   single shared processor this fails: `B.closed = True`, `session_ids = []`.

2. **`test_one_execution_cannot_read_anothers_inputs`** (defect 1).
   Drive two runs to the point of provisioning and assert the `inputs` passed to
   the prompt builder for execution A equals A's inputs. A capturing
   `prompt_builder` is the cleanest probe: `WorkflowExecutionProcessor` takes one
   as a constructor argument (`:135`, wired at `_wiring.py:227`), so the test can
   record what each execution actually provisioned with. Against `b7dbf1c6`
   sharing a processor, A provisions with B's `target` and B's `repos`.

3. **`test_a_processor_refuses_a_second_concurrent_execution`** (step 2).
   Start one `run()`, hold it, call `run()` again on the same instance, assert
   `ProcessorAlreadyRunningError` naming both execution ids. Also assert that a
   *sequential* second `run()` on the same instance still succeeds - the guard
   must forbid concurrency, not reuse.

### 7.2 Dispatcher tests

`apps/syn-api/tests/test_execution_concurrency_posture.py` (or a sibling file):

4. **`test_each_dispatch_gets_its_own_handler`** - a counting factory; two
   dispatches; assert two calls and two distinct handler objects.
5. **`test_the_handler_is_built_inside_the_semaphore`** - with `max_concurrent=1`
   and a blocking handler, assert the factory has been called exactly once while
   the second dispatch is still queued. This is what stops a queued execution from
   holding a `WorkspaceService`.
6. **`test_a_factory_failure_fails_only_that_execution`** - factory raises on the
   first call, succeeds on the second; assert the second execution still runs and
   the dispatcher logged rather than died.
7. Amend the existing `test_the_setting_is_what_bounds_the_dispatcher` for the
   factory signature; keep `test_the_second_execution_waits_for_the_first`
   verbatim in meaning.

### 7.3 Concurrency-restored tests

8. **`test_two_concurrent_dispatches_do_not_cross`** - `max_concurrent=2`, two
   executions of the *same* workflow with different inputs, driven through the
   real `get_execute_workflow_handler` shape with in-memory adapters
   (`APP_ENVIRONMENT=test`). Assert each completes against its own inputs. This is
   the test that licenses raising the default, and it must be added in the same PR
   as step 5.

### 7.4 Pre-PR

`just fitness-check`, `just docs-sync`, `uv run ruff check .`,
`uv run ruff format --check .`. The processor is already near the cognitive budget;
step 2 adds a guard, not a branch inside a hot method, so fitness should hold -
confirm rather than assume.

---

## 8. Sequencing

```
#865 (this design)  ->  restore concurrency  ->  #861 backfill
                                             ->  #867 durable queue  (independent)
```

**#865 before #861.** #861 lands archive-then-confirm-then-stop inside
`_close_phase_workspace_cms` (`:502-532`), the exact loop defect 2 lives in. If
#861 goes first, the archive step inherits the unfiltered iteration and writes
manifest rows - carrying execution id, workspace id, object key and content hash -
attributing one execution's transcripts to another, and archives workspaces whose
agents are still running. Transient mis-teardown becomes a durable
mis-attribution that then has to be repaired. Under Option A the loop's contents
belong to one execution by construction, so #861's ordering is execution-scoped
with no additional work, and #861's reviewer does not have to carry the isolation
question at all.

**#865 and #867 are independent.** #867 is about the window between
`asyncio.Task` creation (`_wiring.py:780-785`) and the semaphore being acquired
(`:795`). `run_workflow()` returns as soon as the task exists, and the dispatch
record is marked `dispatched` on the very next lines
(`packages/syn-domain/src/syn_domain/contexts/github/slices/dispatch_triggered_workflow/projection.py:272-280`:
`await self._execution_service.run_workflow(...)` then `record["status"] =
"dispatched"`), whether or not the execution has started. Nothing in Option A
touches that window, and
#867's durable `queued`/`running` rows do not touch the processor's state. They
compose in the good direction: "build the worker when you claim the durable row"
is Option A's shape, so implementing #867 on top of A means adding a claim step in
front of the existing per-execution construction rather than restructuring a
shared worker.

Ordering note against #866's stated trade: restoring concurrency reduces how much
work sits in #867's window (queueing starts at the Nth execution again rather than
the second), so #865 landing *shrinks* #867 without closing it. #867 should still
be fixed on its own merits; it is not a blocker for either direction.

---

## 9. Restoring concurrency, and rollback

### Restoring (same PR as step 5, after §7.1-7.3 are green)

1. `packages/syn-shared/src/syn_shared/settings/polling.py:111-129` - raise
   `default` from `1` back to `5` and rewrite the description: delete the
   "TEMPORARILY 1 ... #865" paragraph, keep the two genuine scope caveats (it does
   not bound manual executions; it is per-process, not per-cluster).
2. `apps/syn-api/src/syn_api/_wiring.py:761-770` - **keep** the dispatcher's own
   default at `1`. Safe-by-omission is an orthogonal poka-yoke that cost nothing
   and is not what #865 was about. Update its docstring so it no longer reads as a
   #865 mitigation.
3. `apps/syn-api/src/syn_api/services/lifecycle.py:206,290` - delete
   `_log_execution_concurrency_posture` and its call. Warning on every concurrent
   deployment is wrong once concurrency is safe, and a warning that is normal is a
   warning nobody reads.
4. `apps/syn-api/tests/test_execution_concurrency_posture.py:22-41` - delete the
   two posture tests with it. Keep `TestTheDispatcherIsSafeWhenAskedForNothing`
   (still true) and `TestTheConfiguredValueReachesTheDispatcher` (still true).
5. Close #866 as superseded, referencing this PR.
6. No compose file declares `SYN_POLLING_MAX_CONCURRENT_DISPATCHES` (confirmed on
   `b7dbf1c6`), so both live stacks pick up the restored default on next restart
   with no operator action. That is the reason #866 was a default change rather
   than documentation, and the same reason applies in reverse here. Do **not** add
   the variable to compose as part of this work - pinning it would just have to be
   un-pinned later.

### Rollback

- **Operational, no deploy.** Set `SYN_POLLING_MAX_CONCURRENT_DISPATCHES=1` in the
  environment. Restores today's fully-mitigated posture immediately, on both
  stacks, regardless of what the code default says. This is the first response to
  anything unexpected after the default rises.
- **Partial revert.** Revert only step 5's default change (one field in
  `polling.py`). The per-execution construction and the guard stay in; they are
  strictly safer than sharing and there is no reason to revert them.
- **Full revert.** Steps 1-4 are confined to `_wiring.py` (constructor and
  `_run`), two `__init__` lines and one guard in the processor, and the two test
  constructions. A clean `git revert` of the fix PR restores `b7dbf1c6` behaviour.
  If the guard fires in production it means something is sharing a processor -
  that is a real defect being reported, not a reason to remove the guard.

---

## 10. What I could not verify

- **Defect 3 was not reproduced live.** It follows from `phase_id` being a stored
  workflow property and from the writes at `:594-612` / reads at `:710-715`, but I
  did not stand up two concurrent same-workflow runs to observe the overwrite. The
  §7.1 test #1 is written so it would have caught it (same `phase_id`, two
  executions).
- **No production-scale timing.** The 0.508 ms / 0.560 ms figures are from a
  single machine with a local dev Postgres and MinIO, `APP_ENVIRONMENT=test`,
  n=50, warm. They are three orders of magnitude below anything that could matter,
  so I did not pursue a more careful benchmark, but they are not a production
  measurement.
- **The interactive-tmux / multi-agent path was not exercised.** Option A leaves
  `_shared_workspaces` and `_cleanup_shared_workspace` untouched, which is the
  argument that it is safe there, but I ran no interactive-tmux execution. Option
  B *would* change the `shared_cms` identity checks at `:511` and `:953`; that is
  a reason to prefer A, not a verified defect in B.
- **`asyncio.Task` cancellation at shutdown.** `shutdown()` (`:831-835`) cancels
  in-flight tasks. Under Option A a cancelled task's processor is garbage after
  its `finally`; I did not verify that a `CancelledError` raised between
  `_handle_provision` and `_finalize_phase` leaves no container behind. That
  behaviour is identical before and after this change, so it is out of scope - but
  it is a real, separate question, and worth its own issue rather than an
  assumption here.
