# #2122 mutation evidence

| Patch | Source | Test that kills it | Local |
|---|---|---|---|
| 01-compress-resets-mtime.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/local_archive.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 02-no-week-window.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 03-day-window-is-week.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 04-temps-count-as-growth.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 05-references-not-counted.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 06-stored-only-objects.patch | `packages/syn-adapters/src/syn_adapters/session_inventory/archive_usage.py` | `packages/syn-adapters/tests/test_session_archive_usage.py` | killed |
| 07-cache-never-expires.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 08-no-cache.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 09-claim-after-walk.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 10-per-day-is-24h.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 11-runway-when-no-growth.patch | `apps/syn-api/src/syn_api/services/health_probes.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
| 12-health-drops-session-store.patch | `apps/syn-api/src/syn_api/services/lifecycle.py` | `apps/syn-api/tests/test_2107_health_session_store.py` | killed |
