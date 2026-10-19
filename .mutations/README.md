# Mutation evidence for #2030

| Patch | Re-introduces | Killed by |
|---|---|---|
| `01-drop-httpexception-catch.patch` | `http.client.HTTPException` not caught in `main` | `scripts/tests/test_api_shape.py::TestARealReadThatFailsIsNotAbsent::test_a_broken_http_response_exits_two` |
| `02-drop-decode-recursion-catch.patch` | `RecursionError` from `json.loads` not caught in `_fetch` | `scripts/tests/test_api_shape.py::TestARealReadThatFailsIsNotAbsent::test_a_response_too_deep_to_decode_exits_two` |
