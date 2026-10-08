# Type Safety Ratchets: Rationale and the untyped-dicts Gate

> Moved verbatim from AGENTS.md / CLAUDE.md (CLAUDE.md diet, owner review). AGENTS.md keeps a one-line summary and a link here.

## Why the typing ratchets are fitness functions, not lint

Type safety is a declared architectural characteristic of this system, not a
style preference. Python does not enforce it, so it is built in and measured.
That is exactly what a fitness function is: an objective, whole-codebase
measure of a characteristic the architecture requires, ratcheted so it can
only improve.

`untyped-dicts` and the pyright gate are therefore in the same category as
`dependency_direction` and `bounded_context_isolation`, even though the
subject is typing rather than module structure. Do not reclassify them as
"just lint" or "just tests" and do not weaken them on that basis.

The distinction that DOES matter when adding a new check:

| Shape | Category |
|---|---|
| Static property measured across the whole codebase, ratcheted | fitness function - belongs in `ci/fitness/` + `fitness-exceptions.toml` |
| Behavioural assertion about one code path | a test - belongs beside the code |

"Does this specific field have a production consumer" is the second, however
architectural it sounds.

## `untyped-dicts` counts the AST, not the text

`just check-untyped-dicts` parses every file and counts **declarations of
dict-shaped structured state**. The logic and the full definition of what
counts live in `scripts/check_untyped_dicts.py`, pinned by
`scripts/tests/test_check_untyped_dicts.py`.

Three shapes:

| Shape | Counted where | Why |
|---|---|---|
| A str-keyed mapping erased to `Any`/`object` | every written type expression | the structure is gone |
| A `TypedDict`, class-based or functional | its declaration | read as `value["key"]`, validates nothing at runtime |
| A `SimpleNamespace` | every written occurrence | declares no fields at all, so says even less than `dict[str, Any]` |

All spellings of each: plain or dotted, quoted, wrapped across lines, or
renamed — on the import (`from typing import Dict as D`) or by assignment
(`D = dict`, `D: TypeAlias = dict`, `type D = dict`), chains included. Renames
are resolved before names are matched, because a rename is the cheapest dodge
there is: one line, no import, and nothing at the point of use for a reader to
notice. Docstrings and comments are not code and do not count.

A rename is not an alias. `D = dict` writes no type and spends no budget; the
erasure arrives at `D[str, Any]` and is counted there. `D = dict[str, Any]` is
a complete type, so it counts once at that line and not at each use — the same
rule as a `TypedDict`, and for the same reason: the definition is the one place
a fix has to happen.

`NamedTuple` is deliberately **not** counted. It names and types every field
and is read by attribute, so it satisfies both halves of the rule; it is what
you should be converting *to*, alongside `@dataclass` and Pydantic. Its
tuple-ness is a separate concern and does not belong to this gate.

Two ways this gate has been wrong, both found the same way — an agent under
ratchet pressure taking the cheapest green path:

- **It measured spelling** (a regex, until #1188). Renaming `dict[str, object]`
  to `Mapping[str, object]` moved the number without typing anything (PR
  #1186). `Mapping` for a read-only parameter is still the better annotation on
  its merits — it just no longer buys you budget.
- **It measured one shape** (until #1248). A `dict[str, Any]` that failed the
  gate was declared a `TypedDict` instead and it went green (PR #1246), while
  independent review refused the head anyway. So: **a `TypedDict` is not a fix
  for an untyped dict.** Use a `@dataclass` or a Pydantic `BaseModel`.
- **It listed one rename** (caught in review on #1248, before merge). Closing
  the import rename and not `D = dict` would have left every constructor above
  reachable under a name the gate does not know, which is the #1188 defect one
  level up: not a number that moves for a rename, but a number that stays
  still. When you close a spelling, close the class it belongs to.

Both fixes re-baselined the packages rather than raising them — #1188 to 413 /
205 / 139 / 22 / 11, #1248 to 440 / 208 / 146 / 22 / 16. `syn-api` at #1188 is
the finding worth remembering: a third of its untyped surface had never been
visible to the gate. Every one of those is the same debt measured correctly,
never a relaxed ratchet, and the values may only decrease from there.

