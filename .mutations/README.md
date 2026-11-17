# Mutation patches for #2042

Each patch reintroduces part of the bug. Tests: `apps/syn-api/tests/test_2042_large_text_artifacts.py` (unit, no Docker).

| Patch | Bug it restores | Killed by (measured in the implement phase) |
|---|---|---|
| `01-no-inline-threshold.patch` | Text is inline at any size: no `MAX_INLINE_TEXT_BYTES` | `test_large_text_event_is_small_and_still_describes_the_file`, `test_large_text_without_storage_is_refused_not_appended`, `test_restart_path_hands_the_next_phase_the_full_text` |
| `02-handoff-reads-read-model-for-large-text.patch` | The restart handoff reads storage for binary only, so large text reaches the next phase as `""` | `test_restart_path_hands_the_next_phase_the_full_text` |

Run: `just mutation-evidence <PR> "apps/syn-api/tests/test_2042_large_text_artifacts.py" false`
