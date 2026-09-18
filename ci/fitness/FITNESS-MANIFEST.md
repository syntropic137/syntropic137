# Fitness Manifest

Maps architectural principles (from `docs/architecture/architectural-fitness.md`)
to CI-enforced tests. Every principle should have at least one automated check.
If a principle has no test, it is a gap.

Standard: [ADR-062](../../docs/adrs/ADR-062-architectural-fitness-function-standard.md)

Two toolchains enforce fitness:
- **APSS** (`fitness.toml`): Declarative thresholds for complexity, LOC, coupling
- **pytest** (`ci/fitness/`): Structural invariant tests using AST analysis

Run both: `just fitness`

## Quick Reference

| # | Principle | Tests | Config | Status |
|---|-----------|-------|--------|--------|
| 1 | Single Ownership | test_event_ownership, test_event_sourcing_patterns | fitness_exceptions.toml `[event_sourcing_handle_command]` | Enforced |
| 2 | Separation of Concerns | test_layer_separation, test_dependency_direction, test_bounded_context_isolation | fitness_exceptions.toml `[layer_separation, bounded_context_isolation]` | Enforced |
| 3 | Replay Safety | test_esp_fitness (projection purity), test_aggregate_purity | fitness_exceptions.toml `[projection_purity]` | Enforced |
| 4 | Idempotency | test_dedup_durability (F3) | - | Enforced |
| 5 | Startup Contract | test_restart_safety (F2) | - | Enforced |
| 6 | Temporal Clarity | test_projection_wiring (subscriptions) | - | Enforced |
| 7 | Cost Boundaries | test_cost_ceiling (F7) | - | Enforced |
| 8 | Boundary Clarity | test_layer_separation, test_dependency_direction | fitness_exceptions.toml `[layer_separation]` | Enforced |
| 9 | Scalability | test_in_memory_state_audit | fitness_exceptions.toml `[in_memory_state]` | Enforced |
| 10 | Declaration Integrity | test_phase_schema_fields_apply_or_refuse | declared tables in the test | Enforced |
| 11 | Typed Boundaries | test_typed_cross_context_boundaries, test_typed_projection_handlers | fitness_exceptions.toml `[typed_cross_context_boundaries, typed_projection_handlers]` | Enforced |
| 12 | Request Contract Honesty | test_unknown_query_params_rejected | routes discovered from the live app | Enforced |
| 13 | Pointer Reachability | test_submodule_pointer_is_reachable_from_its_default_branch | submodules discovered from .gitmodules | Enforced |
| 14 | Gate Innocence | test_running_the_gates_does_not_modify_the_invoking_repository | the suite itself is the population | Enforced |

### 11. Typed Boundaries (#1268, ADR-063)

A boundary that carries domain meaning must declare its structure. Two gates,
two boundaries: `test_typed_cross_context_boundaries` covers Protocol/ABC
signatures crossing a context line, `test_typed_projection_handlers` covers the
event handlers a projection dispatches.

#1268 was handler parameters reading by string key from events that type every
field. **Most were a bare `dict`, which the per-package ratchet in
`fitness-exceptions.toml` scores as zero by design** - so they were not budgeted
debt, they were unmeasured, and `syn-domain` could have doubled its untyped
handlers without moving 440.

The gate grandfathers what is there and refuses the next one. It is a table
rather than a number, and `test_no_stale_grandfathered_handlers` is what makes
that table ratchet: typing a handler requires deleting its key in the same diff,
so a fixed site cannot leave standing permission to break again. Three waivers
in `fitness-exceptions.toml` had gone stale exactly that way before anything
reported it.

Scope is **every production file**, with no filename filter at all. The gate
first scoped itself to `contexts/*/slices/*/projection.py`, then widened to
"is a projection module" when nine sites turned out to sit one directory
outside - and review then found `projection_adapters.py`, which the gate's own
docstring names as where the dispatch flattens the event and which no spelling
of a filename filter had ever opened. A scope named after a path excuses code
for where it is filed; a scope named after a filename excuses it for what it is
called. What a file is named says nothing, so it is not asked: the population
of files is wide and uninteresting, and the population of *functions* inside
them - decided by the dispatch mechanism - is what the rule is about.

**A gate can be narrower than the claim it makes, and #1281 was both halves of
that at once.** Independent review refused the first head on two findings, and
the lesson generalises past this gate:

- **The population was a list of name prefixes.** `on_`, `_apply_`,
  `_accumulate_` - and not `_on_`, which is what `TriggerQueryProjection` calls
  its five live handlers. Adding `_on_` closes one spelling; the defect is that
  a population decided by what handlers are *called* is evaded by any other
  valid convention, silently. It is now derived from the dispatch mechanisms:
  the protocol entry point, `AutoDispatchProjection`'s `on_*` lookup, any
  function the module names somewhere other than a call site, and the closure
  over anything a handler hands a piece of its own payload to.
- **The rule was a list of rejected spellings, and it contradicted its own
  failure message.** The message says a `TypedDict` is not an acceptable fix;
  converting a parameter to one made the gate green, and three `TypedDict`
  payloads were already live. `object`, `dict[str, str]` and an absent
  annotation were missed the same way. The accepted boundary is now named
  positively - a payload read by attribute that declares its fields - and the
  three ways to fail it are categorical, so there is no list left to be
  incomplete.

That re-baselined the table from 110 to 171. Every one of the 61 was always
this defect; the gate could not see it. Same rule as #1188 and #1248: measured
correctly, never relaxed, down only from here.

**A third finding said the remaining defect was the population, not the
count.** A gate that reports zero over code it never read is worse than no
gate, and cannot be checked by its number. Six more dispatch shapes were
constructed against the head; five are now closed - the filename scope above,
a table holding the function instead of its name (live: nine `_dedup_*`
extractors on the GitHub event pipeline), that table inlined as a local, a
name built from a literal prefix, and `__getattribute__`. That took the table
from 173 to 211 (+38, none removed; 171 above plus the two the binding-form
fix had already added), and retyping the two `TriggerHistoryAdapter` payloads
rather than grandfathering them took `untyped-dicts` `syn-adapters` from 208
to 206.

Three shapes stay open and are now **stated in the gate's docstring with a
test each pinning that it does not see them**: a handler registered by a
decorator, a dispatch table in another module, and anything under `lib/`
(`checkpoint.py`, which defines the `on_*` contract, is in the
event-sourcing-platform submodule and is out of `_PRODUCTION_DIRS` by
construction). The claim the gate makes was narrowed to match: not that the
population is complete, but that *within one production module*, a function
reached by the four mechanisms has every annotated parameter checked. A
documented hole gets fixed; a hole certified as closed does not.

### 10. Declaration Integrity (ADR-069 D5)

A phase schema field may exist only if some code path applies or refuses it.

#1039 was four fields - `input_artifacts`, `allowed_tools`, `execution_type`,
`argument_hint` - validated, persisted, projected, re-exported as YAML, and
dropped before execution. `ExecutablePhase` has one production construction
site, so a field not passed there is inert by construction. Every one of them
had a default, so omitting it was legal Python and legal pyright, and nothing
failed: phases ran, the dashboard rendered the values, the declarations meant
nothing.

The gate classifies every field as applied, refused, or validated, and checks
the classification against the AST rather than against a comment. Both halves
were verified by reintroducing the real defect: an earlier substring-based
version PASSED with #1039 restored, because the command builder mentions
`allowed_tools` whether or not the handler ever sets it. It now asserts the
keyword is passed at the constructor call.

### 13. Pointer Reachability (#1336)

A submodule pointer recorded in this repo must already be merged into that
submodule's own default branch.

Nothing asked before. CI checks the submodule out by SHA, finds it, builds and
goes green whether or not that SHA lives only on a feature branch of the
submodule repo; `check-submodules` asks whether the submodule is initialized and
at its recorded commit, which it is. Merging such a PR leaves main pointing into
an unmerged branch, and every fresh clone breaks as soon as that branch is
deleted or rebased. #1329 is the live instance: green, and unmergeable for
exactly this reason.

**This gate uses the network, and that is the decision, not an accident.** The
property is "has the submodule change landed upstream", and only upstream knows.
Every offline spelling of it interrogates the local clone, which was populated by
the commit under test, so it would report green over precisely the state #1336
describes. There is no honest offline version, only a reassuring one -- see the
ADR-062 amendment.

It is affordable because `fitness-invariants` runs inside `just preflight`, and
preflight already pulls the pinned workspace image and queries the registry. In
CI the owner is the `architectural-fitness` job, which checks out with
`submodules: true` and runs `just preflight`.

**There is deliberately no skip.** An unreachable remote is a FAILED test
carrying git's own stderr. A gate that goes quiet exactly when it cannot see is
the failure mode the issue was filed about, and it would be this one.

The failure message is most of the value: it names the submodule, the SHA, and
the branches that do contain it, so the reader learns "your submodule PR has not
merged yet" rather than "something is wrong". Three shapes are distinguished --
on another branch, on no branch at all (never pushed), and absent from the remote
(rebased away and collected).

**The fetch is not a detail (#1337).** The gate's first revision asked a plain
`git fetch origin` and then for ancestry, and failed all four pointers on its own
CI run while every one was merged. `actions/checkout` runs
`git submodule update --depth=1`, which is shallow *and* single-branch, and takes
the branch tip before the pointer -- so that fetch transfers nothing, the shallow
boundary stands, and tip and pointer sit in two fragments with no path between
them. Ancestry is then not false, it is unanswerable; and with only the default
branch in the refspec, `branch -r --contains` had nothing to name, so the message
degraded to "it has not been pushed" about a commit that was pushed. The fetch
therefore names a full refspec and unshallows, and a guard reports a graph it
could not repair as a gate bug rather than as a verdict. Condition 2 of the
ADR-062 amendment, applied to the local graph: "cannot tell" must not reach a
reader as "no".

### 14. Gate Innocence (#1343)

Running the gates must leave the repository they were run from exactly as they
found it.

This one was not reasoned to, it was hit. The submodule-reachability gates build
git fixtures - `first`, `merged-pointer`, a `feature/not-merged` branch - and
those names turned up in the reflog of a real checkout: `main` force-moved off
`origin/main` onto a synthetic commit, the feature branch moved off its own head,
179 foreign files left untracked. The run reported 706 passed. One `.git` backs
every worktree, so `main` moved for all of them, and the next `git push origin
main` would have pushed the fixture.

**`-C` and `cwd=` were already there and did not help.** git resolves `GIT_DIR`
from the environment before it looks at either, and git exports `GIT_DIR` to
every hook it runs from a worktree - `.githooks/pre-push` runs `just preflight`,
and preflight runs this suite. So the fix is not at the call sites: `conftest.py`
clears the repository-location variables once, for the whole suite, in
`pytest_configure` rather than a fixture, because collection imports modules that
ask git things before any fixture could run.

**The gate asserts the property, not the outcome.** Every gate passed while the
repository was being rewritten, so "does the suite pass" was green throughout and
tells you nothing. This one records the invoking repository's refs, runs the
suite, and compares byte for byte. It runs the suite against a repository built
for the purpose - running it against this checkout to see whether it corrupts
this checkout is the bug, not a test of it - and launches the child the way the
hook does, `GIT_DIR` and all.

**The population is the suite, not the two modules that were caught.** Narrowing
it to the gates that visibly shell out to git would be cheaper and would have a
hole: a gate reaches git through what it imports as readily as through its own
`subprocess` call. Every module under `ci/fitness/` must report tests in the
child's results, so a gate cannot leave the population by quietly collecting
nothing.

### 12. Request Contract Honesty (#1313)

A request that asks for something the server does not implement must be told
so. FastAPI drops an undeclared query parameter rather than refusing it, so a
filter that does not exist read as a filter that matched everything: 200 and an
UNFILTERED page, with nothing in the response to distrust. The failure is
directional -- always MORE rows than asked for, always looking successful --
which is why an agent narrowing to one execution silently got every execution.

`syn_api.strict_query.reject_unknown_query_params` is registered once, as a
global dependency in `create_app()`, and answers 422 naming the unknown key and
listing the accepted ones.

**Why this is a fitness function and not a test beside the fix.** #1263 and
#1306 were both this defect, and both were closed by adding the one missing
parameter to the one endpoint someone had complained about. Neither could catch
the next endpoint. The property is "every route, including the ones not written
yet", so the test DISCOVERS its subjects from the live app instead of listing
them -- a hand-maintained list would have the same half-life as those two
fixes.

**Why this one boots the app.** Every other gate here is static AST analysis.
This property is "the running app answers 4xx", and whether a parameter is
declared is decided by FastAPI's dependency graph at route-construction time,
not by anything visible in a source file. Reading the source could only
re-implement `get_dependant` and would drift from it silently.

## Configuration Surfaces

### 1. `fitness.toml` (APSS declarative thresholds)

Controls complexity, size, and coupling budgets evaluated by `aps run fitness validate .`.

| Rule | Threshold | Level |
|------|-----------|-------|
| Cognitive complexity (function) | <= 15 | error |
| Cyclomatic complexity (function) | <= 10 | error |
| LOC per function | <= 100 | warning |
| LOC per file | <= 750 | error |
| Fan-out per module | <= 30 | error |

Exceptions in `fitness-exceptions.toml` (APSS format, separate from the pytest one).

### 2. `ci/fitness/fitness_exceptions.toml` (pytest structural checks)

Grandfathered violations and registries for pytest-based fitness tests.
Every entry MUST reference a GitHub issue. Budgets are ratchets - they
can only decrease, never increase.

Sections:
- `[layer_separation]` - domain files importing from adapters
- `[bounded_context_isolation]` - files exceeding context import limits
- `[event_sourcing_handle_command]` - direct _handle_command() calls
- `[event_construction_outside_aggregate]` - DomainEvent construction outside aggregates
- `[projection_purity]` - project-specific allowed import prefixes
- `[in_memory_state]` - registry of in-memory state requiring classification

### 3. Inline in test files (being migrated to TOML)

Legacy: some tests define config inline. Being consolidated into
`fitness_exceptions.toml` for single-source-of-truth.

## Test Inventory

### Suite-wide (`ci/fitness/`)

| Test | What it enforces | Principle |
|------|------------------|-----------|
| test_the_gates_leave_the_repository_alone | Running any gate leaves the invoking repository's refs unchanged | 14 |

### Event Sourcing (`ci/fitness/event_sourcing/`)

| Test | What it enforces | Principle |
|------|------------------|-----------|
| test_aggregate_purity | Aggregates: no IO, no async, no infra imports | 3, 8 |
| test_esp_fitness | Projection purity (whitelist), ProcessManager structure | 3 |
| test_event_ownership | Events only constructed in aggregate_*/ dirs | 1 |
| test_event_sourcing_patterns | @command_handler used, not _handle_command() | 1 |
| test_projection_data_flow | Projections declare subscriptions, have names, valid versions | 6 |
| test_projection_registry | Coordinator and manager registry consistent | 6 |
| test_projection_wiring | Correct projection count, unique names, handlers exist | 6 |
| test_aggregate_guards | @command_handler methods have precondition guards before _apply() | 1 |
| test_restart_safety | Catch-up replay produces zero process_pending() calls | 3, 5 |
| test_dedup_durability | Pipeline uses durable, content-based dedup; dedup port is wired | 4 |

### Code Quality (`ci/fitness/code_quality/`)

| Test | What it enforces | Principle |
|------|------------------|-----------|
| test_bounded_context_isolation | Max N foreign context imports per file | 2, 8 |
| test_dependency_direction | Package hierarchy: shared -> domain -> adapters -> api | 2, 8 |
| test_layer_separation | Domain doesn't import adapters/API at runtime | 2, 8 |
| test_error_propagation | No silent except: pass handlers | 2 |
| test_in_memory_state_audit | Every in-memory state var is classified | 9 |

### API (`ci/fitness/api/`)

| Test | What it enforces | Principle |
|------|------------------|-----------|
| test_background_task_safety | BackgroundTasks closures handle errors | 2 |
| test_cost_query_separation | Cost routes use query services, not projection stores | 8 |
| test_prefix_resolver_coverage | GET /{id} endpoints use resolve_or_raise() | 8 |
| test_cost_ceiling | Dispatch chain has rate limit + budget check wired, config bounded | 7 |
| test_unknown_query_params_rejected | Every route refuses a query parameter it does not declare | 12 |

### Infrastructure (`ci/fitness/infrastructure/`)

| Test | What it enforces | Principle |
|------|------------------|-----------|
| test_compose_consistency | Docker Compose valid, build args match Dockerfiles | 8 |
| test_phase_definition_roundtrip | PhaseDefinition serialization is lossless | 8 |
| test_proxy_hostname_agreement | Envoy/injector/proxy URL configs agree | 8 |

## Writing New Fitness Tests

Every fitness test file follows this contract:

1. **One file per invariant.** Don't combine unrelated checks.
2. **Config in TOML.** Whitelists, registries, and exceptions go in `fitness_exceptions.toml`.
3. **Reference the principle.** Docstring names which of the 9 principles it enforces.
4. **Actionable failures.** Messages explain HOW to fix, not just WHAT failed.
5. **Use `@pytest.mark.architecture`** on every test class.
6. **Static over dynamic.** Prefer AST analysis. Integration tests get `@pytest.mark.integration`.

```python
"""Fitness function: <name>.

<What invariant this enforces.>
Principle: <N>. <Name> (docs/architecture/architectural-fitness.md)
"""

import pytest
from ci.fitness.conftest import repo_root, production_files, load_exceptions, rel_path

@pytest.mark.architecture
class TestMyInvariant:
    def test_the_thing(self) -> None:
        """<What this checks.>"""
        # ... AST analysis, import checking, grep, etc.
        if violations:
            pytest.fail(
                f"Found {len(violations)} violation(s):\n"
                f"  {joined}\n\n"
                "To fix: <specific instructions>"
            )
```

## Shared Helpers (`ci/fitness/conftest.py`)

- `repo_root()` - repository root Path
- `production_files(root)` - all .py files under apps/*/src and packages/*/src
- `load_exceptions(root)` - full fitness_exceptions.toml as dict
- `rel_path(path, root)` - normalize path for exception key lookup

## Shared Utilities

- `ci/fitness/_imports.py` - AST-based import analysis (ImportInfo, extract_imports, runtime_imports)
- `ci/fitness/_event_discovery.py` - scan domain/events/ for @event-decorated classes
- `ci/fitness/event_sourcing/conftest.py` - aggregate_files() discovery
