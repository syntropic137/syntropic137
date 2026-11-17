# Mutation evidence for #1424 part 2 (conversation log behind a port)

| Patch | Re-introduces | Test meant to kill it |
|---|---|---|
| `01-route-imports-codex-stream.patch` | the route importing `syn_shared.codex_stream` again | `ci/fitness/code_quality/test_harness_format_boundary.py::test_harness_formats_stay_in_adapters_and_inference_has_one_owner` (zero-tolerance now the exemption is gone) |
| `02-tool-result-drops-error-flag.patch` | a Claude `tool_result` with `is_error: true` previewed without `[error]` | `packages/syn-adapters/tests/test_conversation_log_reader.py::test_claude_tool_result_list_content_and_is_error` |
| `03-codex-noise-kept.patch` | Codex CLI banner lines kept in the log | `packages/syn-adapters/tests/test_conversation_log_reader.py::test_codex_cli_noise_does_not_belong_in_the_log` |

All three are dockerless (`just mutation-evidence <pr> "<ids>" false`).
