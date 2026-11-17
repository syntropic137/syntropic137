# Mutation evidence for #935

| Patch | Restores | Test meant to kill it |
|---|---|---|
| `01-scanner-accepts-every-valid-event-type.patch` | the old `VALID_EVENT_TYPES` gate in `EmbeddedEventScanner` | `test_embedded_event_scanner.py::TestToolOutputIsNotBilling` (`test_embedded_cost_events_record_nothing`, `test_execution_totals_count_the_delegate_once`) |

Run locally in the workspace, with the patch applied: both tests fail. The cost
test reads `Decimal('1.5') != Decimal('1.25')`, which is #935's double count.
