# Codex access tokens: setup and validation

**Closes [#893](https://github.com/syntropic137/syntropic137/issues/893).** Requires a ChatGPT **Business or Enterprise** workspace; not available on Plus or Pro.

## Why this and not the alternatives

A ChatGPT account has **one credential lineage**. Verified 2026-08-27: a second `codex login` revokes the first server-side, killing the access token too, not just the refresh token. So:

- **Copying `auth.json` into a vault can never be durable.** Any `codex login` or `codex logout` anywhere kills the copy. This is the failure that has recurred every few days.
- **Write-back does not fix it** either, because it assumes the deployment is the only thing that ever authenticates. The moment a developer runs codex on their laptop, the deployment is revoked.
- **An API key would work** but bills OpenAI API usage instead of drawing on the Codex plan, which is the wrong economics here.

An access token is a workspace credential managed from the admin console, with its own expiry and its own revocation. Nothing a developer does at a terminal touches it. It stays on ChatGPT-plan billing.

> *"Use them when a script, scheduled job, or CI runner needs repeatable local access... without a user completing a browser sign-in."*
> [learn.chatgpt.com/docs/enterprise/access-tokens](https://learn.chatgpt.com/docs/enterprise/access-tokens)

## Create the token

1. ChatGPT admin console, **Access tokens**.
2. Name it for the deployment, not the person. `syntropic137-macmini` beats `neural-token`, because the point is that it is not tied to a human.
3. Expiry: **No expiration** for a deployment, or 90 days if policy requires rotation. The shortest available is one day.
4. **Copy it immediately.** It cannot be viewed again after the modal closes.

If your workspace exposes service accounts, create the token from a service-account identity rather than your own. A token tied to a human is one offboarding away from an outage.

## Install it

The platform treats `CODEX_AUTH_JSON` as an opaque blob and never inspects `auth_mode` or `tokens`, so this is a **vault value change with no code change**.

Produce an auth.json in access-token form, then use its contents as the vault value:

```bash
printf '%s' "$CODEX_ACCESS_TOKEN" | codex login --with-access-token
just codex-auth-clip --dotenv     # clipboard gets the .env-ready line
```

Paste into the root `.env`, replacing the existing `CODEX_AUTH_JSON=` line, then:

```bash
just dev-down && just dev
```

The rebuild is not optional. Environment is fixed when a container is created, and `docker restart` reuses the existing environment.

## Validate it, in this order

Each step answers a different question. Do not skip to the last one.

### 1. The token reached the container

```bash
docker exec syn-api python3 -c "
import os, json, hashlib
v = os.environ.get('CODEX_AUTH_JSON','')
print('bytes:', len(v))
d = json.loads(v) if v else {}
print('auth_mode:', d.get('auth_mode'))
print('sha:', hashlib.sha256(v.encode()).hexdigest()[:16])
"
```

Expect a non-zero length and an `auth_mode` reflecting token auth. Compare the sha against what you pasted.

### 2. A codex phase runs

```bash
syn workflow run codex-delegates-to-claude
```

Expect the phase to complete with `agent_model=gpt-5.6-sol` and a non-zero cost. A `refresh_token_reused` or `revoked` error here means the vault value did not take, not that the token is bad.

### 3. THE POINT OF THE WHOLE EXERCISE: a developer login does not break it

This is the property you are buying, and it is the only step that proves it.

```bash
# on a laptop, while the deployment credential is installed
codex login
```

Then re-run step 2 against the deployment. **The phase must still succeed.**

If it fails, the access token shares a lineage with user sessions after all, and the entire premise is wrong. Say so loudly rather than working around it, because every plan built on top of this assumes independence.

> The documentation does not explicitly state that access tokens survive a user
> `codex login` or `codex logout` in the same workspace. It is strongly implied,
> since they are admin-console managed with independent expiry and revocation,
> but implied is not verified. **Step 3 is the verification.** Run it once,
> deliberately, before trusting the arrangement.

### 4. It survives a container recycle

```bash
just dev-down && just dev
syn workflow run codex-delegates-to-claude
```

Confirms nothing depended on in-container state that teardown discards, which was the failure mode of the copied-credential arrangement.

## Operating notes

- **Rotation.** With "No expiration" there is no forced rotation, so put a calendar reminder on it anyway. A credential nobody has ever rotated is a credential nobody knows how to rotate.
- **Revocation is the fire drill.** Revoking from the admin console is how you kill a compromised deployment credential without touching anyone's personal session. That is the other half of what you are buying.
- **Keep it out of logs.** The staging path already handles this: the token is written to `/workspace/.setup/codex-auth.json`, installed to `~/.codex/auth.json` at 0600, and the staged copy removed, with a fail-closed assertion. Never pass it in argv.
- **`just codex-auth-clip` still works** and still reports freshness. Its JWT expiry decode degrades to silence when `tokens` is absent, so an access-token auth.json will simply report less, not error.

## What this does not solve

Nothing about delegation. A delegated `codex exec` inside a workspace still needs
`--dangerously-bypass-approvals-and-sandbox`, and delegated child sessions are
still uncaptured ([#895](https://github.com/syntropic137/syntropic137/issues/895)).
This fixes who the container is, not what happens once it runs.
