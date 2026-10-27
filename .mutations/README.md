# Mutation evidence, #2108 S4 (PR #2135)

One bug per patch, against scripts/eval_referee.py and scripts/implementer_scorer.py.
Named tests: scripts/tests/test_eval_referee.py, scripts/tests/test_eval_implementer.py,
scripts/tests/test_eval_referee_on_docker.py.

| Patch | Bug |
|---|---|
| 01 | offline check runs before the network is cut |
| 02 | any interface list containing lo reads as offline |
| 03 | RESULT line trusted when the exit code disagrees |
| 04 | controls gate off: patches scored after a failed control |
| 05 | bundles hold only the pin's submodule gitlinks, not the fix's |
| 06 | temporary bundle refs left behind |
| 07 | only the first artifact page is read |
| 08 | failed cleanup does not withhold the verdict |
| 09 | container/network removal not retried |
| 10 | fetched patch bytes replaced, not carried |
| 11 | read_patch reads text (newline translation, strict decode) |
| 12 | git() stdout decoded with replacement |
| 13 | git() stdin encoded with replacement |
| 14 | conftest.py not judged at the fix |
| 15 | pytest.toml not judged at the fix |
| 16 | tracked paths changed by the patch ignored (rename source missed) |
| 18 | prepared tree without .venv accepted |
| 19 | a prepared tree scores a second patch |

No 17: dropping `--no-renames` is equivalent. `git apply` without `--index`
leaves a rename's destination untracked, so `git diff HEAD` lists the deleted
source either way.
