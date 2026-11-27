# Mutation evidence for #1661 slice 3 (lifecycle webhook wiring)

Run with no Docker needed:

```
just mutation-evidence <PR> "packages/syn-adapters/tests/test_1661_lifecycle_webhook_wiring.py packages/syn-shared/tests/test_lifecycle_webhook_settings.py apps/syn-api/tests/test_1661_lifecycle_webhook_startup_gate.py" false
```

| Patch | Bug | Killed by |
|---|---|---|
| `01-lifecycle-registration-dropped.patch` | settings read, manager never appended to the registry | `test_configured_registers_one_manager_that_posts_signed_to_the_url` |
| `02-lifecycle-half-config-check-removed.patch` | one variable set silently means off | `test_half_configured_refuses_to_build_the_registry[*]`, `test_only_the_url_names_the_missing_secret`, `test_only_the_secret_names_the_missing_url`, `test_a_secret_with_no_url_stops_the_critical_path_before_the_event_store` |
| `03-lifecycle-registered-when-unconfigured.patch` | manager registered with nothing configured | `test_unconfigured_registers_no_manager_and_says_so_once` |
