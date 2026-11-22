# Mutation evidence for #2345

| Patch | Re-introduces | Killed by |
|---|---|---|
| `01-lease-released-before-teardown.patch` | `_drive` cancelling the LeaseKeeper as soon as the drain returns, so the reap and close run unrenewed (main's behaviour) | `test_lease_through_teardown.py::test_a_teardown_longer_than_the_lease_ttl_is_neither_fenced_nor_interrupted` |
| `02-renewal-behind-close-reported-as-loss.patch` | `LeaseKeeper.hold` treating a renewal refused because the close just released the row as a lost lease | `test_lease_through_teardown.py::test_a_renewal_refused_because_the_close_released_the_row_is_not_a_lost_lease` |
