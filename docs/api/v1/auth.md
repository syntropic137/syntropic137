# auth

Authentication context for API operations.

## AuthContext

All v1 functions accept an optional `AuthContext` parameter. When `None` (the default), operations run without authorization checks.

```python
from aef_api import AuthContext

@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: str
    tenant_id: str | None = None
    roles: frozenset[str] = frozenset()
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `user_id` | `str` | required | Authenticated user identifier |
| `tenant_id` | `str \| None` | `None` | Tenant for multi-tenant isolation |
| `roles` | `frozenset[str]` | `frozenset()` | Role names for authorization |

### Usage

```python
from aef_api import AuthContext

# Unauthenticated (default)
result = await aef_api.v1.workflows.list_workflows()

# Authenticated
auth = AuthContext(
    user_id="user-123",
    tenant_id="tenant-abc",
    roles=frozenset({"admin", "operator"}),
)
result = await aef_api.v1.workflows.list_workflows(auth=auth)
```

### Future Plans

Phase 2+ will wire AuthContext to real identity providers and implement authorization checks per operation.
