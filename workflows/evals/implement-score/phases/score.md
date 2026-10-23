# Score one implementer-seed patch

You run a scorer and report its result. You do not judge the patch, fix it,
or edit it. The verdict is the scorer's exit code and nothing else.

- Case id: $ARGUMENTS
- Execution scored: {{implement_execution_id}}

## 1. Get the patch

Write it to `/workspace/artifacts/output/implement.patch`, byte for byte.

- If the `patch` input is not empty, it is everything strictly between the two
  marker lines below. Write it with the Write tool exactly as given, ending
  with a single newline. Then check it:
  `sha256sum /workspace/artifacts/output/implement.patch` must equal
  `{{patch_sha256}}`. If it does not, write `RESULT: ERROR` ("patch transfer
  mismatch") and stop. Never score a patch whose hash does not match.

=====BEGIN-PATCH-7f3c=====
{{patch}}
=====END-PATCH-7f3c=====

- Otherwise fetch it over the read-only platform API. `$SYN_API_URL` and
  `$SYN_API_TOKEN` are set when this deployment grants API access:

  ```
  GET $SYN_API_URL/api/v1/executions/{{implement_execution_id}}
      -> phases[] where phase_id == "implement": artifact_id
  GET $SYN_API_URL/api/v1/artifacts/{artifact_id}/content -> content
  ```

  Send `Authorization: Bearer $SYN_API_TOKEN`. A 202 means retry after 2 s.
  If the execution has several artifacts, use the one that holds
  `implement.patch`.

- If there is no `patch` input and no API access, or the phase has no patch,
  write `RESULT: ERROR` with the reason to the output below and stop. Never
  reconstruct or guess a patch. A missing patch from a completed implement
  phase is `RESULT: FAIL` ("no change"), not an ERROR. Say which it is.

## 2. Score

From the repository root under `/workspace/repos/`:

```
uv run python scripts/eval_implementer.py score --case $ARGUMENTS \
  --patch /workspace/artifacts/output/implement.patch
```

Exit 0 is PASS, 1 is FAIL, 2 is ERROR. Run it once. Re-run only on ERROR,
and only once.

## 3. Output

Write `/workspace/artifacts/output/score.md`. The first line must be exactly
one of `RESULT: PASS`, `RESULT: FAIL` or `RESULT: ERROR`. Then add:

- the case id and the execution id scored;
- the sha256 of the patch file, and its size in bytes;
- the scorer's full stdout and stderr in a fenced block.

Do not commit, push, comment, or open or edit any issue or pull request.
