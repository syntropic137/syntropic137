# Mutation patches for #2042

Each patch reintroduces part of the bug. Tests: `apps/syn-api/tests/test_2042_large_text_artifacts.py` (unit, no Docker).

| Patch | Bug it restores | Killed by (measured in the implement phase) |
|---|---|---|
| `01-no-inline-threshold.patch` | Text is inline at any size: no `MAX_INLINE_TEXT_BYTES` | `test_large_text_event_is_small_and_still_describes_the_file`, `test_large_text_without_storage_is_refused_not_appended`, `test_restart_path_hands_the_next_phase_the_full_text` |
| `02-handoff-reads-read-model-for-large-text.patch` | The restart handoff reads storage for binary only, so large text reaches the next phase as `""` | `test_restart_path_hands_the_next_phase_the_full_text` |

Run: `just mutation-evidence <PR> "apps/syn-api/tests/test_2042_large_text_artifacts.py" false`

Added in fix round 1 (verification finding on `get_for_phase_injection`):

| Patch | Bug it restores | Killed by (measured in fix round 1) |
|---|---|---|
| `03-prompt-substitution-skips-large-text.patch` | Prompt substitution skips text with empty inline content, so a large primary is dropped (or loses to a small secondary) | `test_prompt_substitution_gets_the_full_text_of_a_large_primary[sole-large]`, `test_prompt_substitution_gets_the_full_text_of_a_large_primary[large-primary-small-second]` |

Correction to the table above, measured by verification: patch 01 is killed by the first two tests named, not by `test_restart_path_hands_the_next_phase_the_full_text`. With no threshold the text is inline, so that reader gets it anyway.
