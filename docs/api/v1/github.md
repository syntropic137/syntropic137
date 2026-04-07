# github

GitHub App integration — repositories, installations, and triggers.

**Status:** Partially implemented — `list_repos()` is live; remaining functions return `Err(GitHubError.NOT_IMPLEMENTED)`.

## list_repos()

List GitHub repositories accessible via the GitHub App. Returns repository metadata (name, owner, visibility, default branch, URL) for all installations, optionally filtered by `installation_id`.

**Route:** `GET /api/v1/github/repos`

**Signature:**

```python
async def list_repos(
    installation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,
) -> Result[list[dict[str, Any]], GitHubError]
```

---

## get_installation()

Get details about a GitHub App installation.

**Signature:**

```python
async def get_installation(
    installation_id: str,
    auth: AuthContext | None = None,
) -> Result[dict[str, Any], GitHubError]
```

---

## register_trigger()

Register a GitHub event trigger for a workflow.

**Signature:**

```python
async def register_trigger(
    repo_owner: str,
    repo_name: str,
    event_type: str,
    workflow_id: str,
    config: dict[str, Any] | None = None,
    auth: AuthContext | None = None,
) -> Result[str, GitHubError]
```
