# Testing codex device auth: does a second login get its own refresh lineage?

**Time: about 5 minutes. Cost: nothing. Reversible.**

This settles the one question blocking [#893](https://github.com/syntropic137/syntropic137/issues/893), which no OpenAI documentation answers.

## The question

`CODEX_AUTH_JSON` in the vault is a **copy** of a laptop's `~/.codex/auth.json`. Both hold the same OAuth refresh token, and refresh tokens are single-use: redeeming one issues a new pair and kills the old.

So when the laptop rotates, the vault copy dies. That is what happened: the vault held an Aug 8 copy, the laptop rotated Aug 24, and the container failed with `refresh_token_reused`.

**The question is whether `codex login` a second time mints an independent refresh chain**, or whether an account has exactly one.

- **Independent** -> mint a credential the laptop never touches, and laptop rotations stop killing it.
- **Shared** -> copying can never work, and the fix has to be write-back or a different auth mode.

Device auth is just the OAuth Device Authorization Grant: you approve on a second device because the first has no browser. **It is a different way to obtain tokens, not a different kind of token.** The result is an ordinary rotating pair. Nothing about it is device-bound, so it is only useful here if lineages turn out to be independent.

## Before you start

Record what the current token is, so you can tell whether it survives. **This prints hashes, never the token.**

```bash
python3 -c "
import json, hashlib, pathlib, base64, time
d = json.loads((pathlib.Path.home()/'.codex'/'auth.json').read_text())
t = d.get('tokens') or {}
print('refresh_token sha:', hashlib.sha256(t.get('refresh_token','').encode()).hexdigest()[:12])
print('last_refresh     :', d.get('last_refresh'))
at = t.get('access_token','')
if at.count('.') == 2:
    b = at.split('.')[1]; b += '=' * (-len(b) % 4)
    c = json.loads(base64.urlsafe_b64decode(b))
    print(f'access expires in: {(c[\"exp\"]-time.time())/3600:.1f}h')
"
```

Then back it up, because step 2 overwrites it:

```bash
cp ~/.codex/auth.json ~/.codex/auth.json.pre-device-test
```

## Step 1: confirm the vault copy currently works

Skip if you already know it does. This is the control: if it is already broken, the test proves nothing.

```bash
just codex-auth-clip          # reports expiry before you paste anything
```

If it says `EXPIRED`, stop and re-mint before testing anything else.

## Step 2: mint a second credential

```bash
codex login --device-auth
```

Approve it in the browser. This **overwrites `~/.codex/auth.json`** with the new credential, which is why you backed it up.

Record the new hash with the same snippet as above. **The hash must differ.** If it is identical, codex reused the existing credential and the test is void.

## Step 3: the decisive check

Put the OLD credential back in place and see whether it still authenticates.

```bash
cp ~/.codex/auth.json ~/.codex/auth.json.device-minted   # keep the new one
cp ~/.codex/auth.json.pre-device-test ~/.codex/auth.json # restore the old one

codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check \
  -C /tmp "reply with the single word OK and nothing else" < /dev/null
```

### Reading the result

**`OK` comes back** -> the old credential survived a second login. **Lineages are independent.** The device-minted credential is safe to put in the vault and the laptop will not kill it.

**A 401 / `refresh_token_reused`** -> the second login invalidated the first. **One lineage per account.** Copying a credential anywhere can never be durable, and #893 needs write-back or a different auth mode.

## Step 4: if independent, install it

```bash
cp ~/.codex/auth.json.device-minted ~/.codex/auth.json  # optional: keep using it locally
just codex-auth-clip --dotenv                            # writes the .env-ready line to the clipboard
# paste into the root .env, replacing the CODEX_AUTH_JSON line
just dev-down && just dev                                # env is fixed at container-create time
```

Then restore your everyday credential if you swapped it:

```bash
cp ~/.codex/auth.json.pre-device-test ~/.codex/auth.json
```

## What this does NOT solve, either way

**A container still rotates the token when the access token expires, and throws the result away at teardown.** Access tokens live 240 hours (10 days), and a run inside that window does not refresh at all - verified 2026-08-27 by running codex in the workspace image and confirming `auth.json` was byte-identical afterwards.

So even with independent lineages you get roughly ten days before the vault copy goes stale again. Device auth converts *"breaks whenever the laptop rotates"* into *"breaks predictably every ten days"*.

**The durable fix is write-back**: whatever runs the containers persists the rotated `auth.json` instead of discarding it. That belongs to the deployment, not to any laptop, and it is what makes this work on a Mac Mini or anywhere else. This test determines how much write-back has to handle, not whether it is needed.

## Cleanup

```bash
rm -f ~/.codex/auth.json.pre-device-test ~/.codex/auth.json.device-minted
```

Both files contain live credentials. Do not leave them lying around, and do not put them anywhere git can see.
