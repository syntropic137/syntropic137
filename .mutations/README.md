# Mutation evidence for #2106

Each patch is a mutation of non-test source on the PR head. The runner reads
only `*.patch`; this file maps each one to the tests meant to kill it. Delete
`.mutations/` after the evidence comment reports PASS for the head SHA.

Docker: `false`. The tests parse source strings only.

Node ids contain spaces and an apostrophe: pass the whole module
(`scripts/tests/test_check_version_literals.py`) if the runner splits on spaces.

| Patch | Mutates | Killed by |
|---|---|---|
| `01-nonlocal-read-ignored.patch` | `_owner` no longer honours an explicit `nonlocal` read | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[nonlocal read under a class that declares global]` |
| `02-class-read-never-falls-through.patch` | a class-body read of a name it binds sees only the class | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[class rebinds the outer name to itself]`, `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[class rebinds a module name an enclosing function shadows]` |
| `03-class-read-falls-to-enclosing-scope.patch` | that read falls to the enclosing scope, not the module (the pre-#2106 behaviour) | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[class rebinds a module name an enclosing function shadows]`, `scripts/tests/test_check_version_literals.py::test_clean_source_is_not_flagged[class rebinds a module name over an enclosing function's import]` |

Dispatch:

```
just mutation-evidence <PR> "scripts/tests/test_check_version_literals.py" false
```
