# Mutation evidence for #2106

Each patch is a mutation of non-test source on the PR head. The runner reads
only `*.patch`; this file maps each one to the tests meant to kill it. Delete
`.mutations/` after the evidence comment reports PASS for the head SHA.

Docker: `false`. The tests parse source strings only.

Node ids contain spaces and an apostrophe: pass the whole module
(`scripts/tests/test_check_version_literals.py`) if the runner splits on spaces.

| Patch | Mutates | Killed by |
|---|---|---|
| `01-nonlocal-name-counts-as-local.patch` | a name declared `nonlocal` counts as local to the scope that declares it | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[nonlocal read under a class that declares global]` |
| `02-class-read-never-falls-through.patch` | a class-body read of a name it binds sees only the class | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[class rebinds the outer name to itself]`, `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[class rebinds a module name an enclosing function shadows]` |
| `03-class-read-falls-to-enclosing-scope.patch` | that read falls to the enclosing scope, not the module (the pre-#2106 behaviour) | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[class rebinds a module name an enclosing function shadows]`, `scripts/tests/test_check_version_literals.py::test_clean_source_is_not_flagged[class rebinds a module name over an enclosing function's import]` |
| `04-class-declarations-reach-methods.patch` | a class body's `global` applies to the functions nested in it | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[method reads past a class that declares the name global]`, `scripts/tests/test_check_version_literals.py::test_clean_source_is_not_flagged[method reads the enclosing function past a class's global]` |
| `05-no-class-cell.patch` | no implicit `__class__` cell for functions in a class body | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[__class__ of a FastAPI subclass]`, `scripts/tests/test_check_version_literals.py::test_clean_source_is_not_flagged[module __class__ is not a method's cell]` |
| `06-no-name-mangling.patch` | `__x` in a class is never read as `_Class__x` | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[mangled private name in a class body]`, `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[mangled private name in a method]`, `scripts/tests/test_check_version_literals.py::test_clean_source_is_not_flagged[mangled name is not the unmangled import]` |
| `07-inlined-comprehension-sees-cell.patch` | a list comprehension in a class body reads the `__class__` cell (it is inlined, PEP 709) | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[class-body list comprehension reads the module __class__]`, `scripts/tests/test_check_version_literals.py::test_clean_source_is_not_flagged[class-body list comprehension does not read the cell]` |
| `08-nonlocal-class-store-misses-cell.patch` | a `nonlocal __class__` store misses the cell | `scripts/tests/test_check_version_literals.py::test_planted_fastapi_version_is_caught[nonlocal __class__ rebinds the cell]` |

Dispatch:

```
just mutation-evidence <PR> "scripts/tests/test_check_version_literals.py" false
```
