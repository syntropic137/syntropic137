"""Keeping a workspace's git credential usable for as long as the workspace is (#1393).

THE CREDENTIAL DIES BEFORE THE CONTAINER DOES. A phase's git credential is a
GitHub App installation token, minted once while the workspace is being
provisioned and written into ``~/.git-credentials`` by the setup phase. GitHub
caps those at one hour and will not extend one. A phase's ``timeout_seconds``
is 3600 on top of the setup phase's own budget, so a phase that runs to its
limit has, by arithmetic alone, outlived the only credential in its container.

THAT IS WHY THE SAFETY NET FAILED AND THE AGENT'S OWN PUSH DID NOT. Both
resolve the identical entry from the identical file - there is no second
credential path and never was. What separates them is WHEN they run: the
agent pushes somewhere in the middle of the phase, and the unpushed-work
guard's quarantine push runs at teardown, by construction the last moment of
the longest phases. On `exec-db6f687e991a` the ordinary push landed and the
quarantine push, minutes later, was answered "Invalid username or token".

SO THE CREDENTIAL IS RE-MINTED RATHER THAN THE PUSH BEING RETRIED. A retry
that parsed git's stderr for the word "authentication" would be guessing at a
message git is free to reword, and would still be holding the expired token
on the second attempt. Minting a fresh one costs a single API call on a path
that only runs when a phase is already ending, and it is unconditional:
nothing here asks whether the token has expired, because an answer to that
question would be a second thing that can be wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    CredentialRenewalFailedError,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        ExecutionResult,
    )

logger = logging.getLogger(__name__)

#: Where the renewal script is staged, under the same ``.setup`` directory the
#: setup phase uses and which `clear_secrets` already empties. The script
#: carries the token in its text, exactly as the setup script does, so it goes
#: in as a FILE rather than as argv: a command line is readable through
#: ``docker inspect`` and every process listing in the container, and a file
#: written 0600 by a script that deletes itself is not.
_SCRIPT_PATH = ".setup/renew-credential.sh"

#: Generous for `git config` and two `printf`s, short enough that a wedged
#: container cannot hold the teardown path open. The callers are already under
#: their own bounds; this one is so that a renewal cannot be the thing that
#: outlasts them.
_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class CredentialSource:
    """What it takes to mint this workspace's git credential again.

    Recorded when the setup phase runs, because that is the only moment that
    holds both the workspace and the answers - and because a renewal that
    guessed either of them would hand the phase a DIFFERENT credential from
    the one it was provisioned with. ``can_open_pr`` in particular decides
    what the token is allowed to do (#1197): re-minting without it would
    quietly promote a phase that was deliberately denied publication.
    """

    repositories: tuple[str, ...]
    can_open_pr: bool


async def renew_git_credential(workspace: ManagedWorkspace, source: CredentialSource) -> None:
    """Mint this workspace a fresh git credential and install it, or raise.

    Raises:
        CredentialRenewalFailedError: the credential in this container is not
            known to be usable, and THE ONLY THING this can raise. Minting
            failed, the script could not be put in the container, running it
            failed, or it exited non-zero - four causes, one outcome, because
            the callers can do nothing different about them and a fifth kind
            of failure escaping as itself is one neither of them catches.
            Deliberately NOT swallowed here: the two want opposite things from
            a failure - the startup check fails the phase on it, the
            quarantine path logs it and pushes anyway on the chance the old
            token has life left - and only they can decide that.
    """
    from syn_adapters.workspace_backends.service import SetupPhaseSecrets

    try:
        secrets = await SetupPhaseSecrets.create(
            repositories=list(source.repositories),
            # The credential and nothing else. A renewal re-runs over a
            # workspace whose repositories are already on disk, and re-cloning
            # them would be both wasteful and, on the teardown path, capable of
            # overwriting the very work being rescued.
            clone_repos=False,
            can_open_pr=source.can_open_pr,
            require_github=bool(source.repositories),
        )
    except Exception as unmintable:
        raise CredentialRenewalFailedError(
            f"a fresh GitHub installation token could not be minted ({unmintable})"
        ) from unmintable

    if not secrets.repo_tokens:
        # No repository is credentialed, so there is no credential to renew and
        # nothing downstream depends on one. Distinct from a renewal that was
        # attempted and failed, and must not be reported as one.
        logger.debug("No git credential to renew for workspace %s", workspace.workspace_id)
        return

    try:
        result = await _install(workspace, secrets.build_credential_script())
    finally:
        # The script holds the token in plain text, so removing it is not
        # tidiness. In a `finally` because a script that failed part-way is
        # exactly as readable as one that succeeded.
        await _remove_script(workspace)

    if result.exit_code != 0:
        raise CredentialRenewalFailedError(
            f"the credential script exited {result.exit_code}: "
            f"{result.stderr.strip() or '(no stderr output)'}"
        )
    logger.info("Renewed the git credential in workspace %s", workspace.workspace_id)


async def _install(workspace: ManagedWorkspace, script: str) -> ExecutionResult:
    """Put the script in the container and run it, or raise the promised error.

    EVERY WAY THIS CAN FAIL IS THE SAME FAILURE to the callers: the credential
    in the container is not known to be usable. Both of these calls reach a
    container through an isolation provider, so both can raise whatever that
    provider raises - a docker API error, a timeout, a handle for a container
    that has already gone. Letting one of those through as itself would have
    been a third outcome nobody catches, and at teardown that is the whole
    bug this module exists to fix arriving by another door: `_quarantine`
    catches `CredentialRenewalFailedError` and would abort on anything else,
    skipping the rescue push entirely rather than spending the old token on it.
    A workspace that will not take a file is a workspace that did not get a
    new credential, which is exactly what the error says.
    """
    try:
        await workspace.inject_files([(_SCRIPT_PATH, script.encode())], base_path="/workspace")
        return await workspace.execute(
            ["bash", f"/workspace/{_SCRIPT_PATH}"], timeout_seconds=_TIMEOUT_SECONDS
        )
    except Exception as uninstallable:
        raise CredentialRenewalFailedError(
            f"the credential script could not be installed and run ({uninstallable})"
        ) from uninstallable


async def _remove_script(workspace: ManagedWorkspace) -> None:
    """Delete the staged script, and never let that deletion be the verdict.

    LOGGED, NOT RAISED, for two different reasons that happen to agree. A
    cleanup that fails AFTER a successful renewal would otherwise report a
    usable credential as unusable - and at startup that refuses a phase that
    could have saved its work. A cleanup that fails after a FAILED renewal
    would replace the real reason with itself, which is the masking a bare
    `finally` around a raising call always does.

    The token left behind is a real cost and is why this is ERROR rather than
    a shrug: it sits 0600 in a `.setup` directory that `clear_secrets` also
    empties, inside a container that is about to be destroyed on the teardown
    path. That is worth an operator's attention and is not worth losing a
    phase's work over.
    """
    try:
        await workspace.execute(["rm", "-f", f"/workspace/{_SCRIPT_PATH}"])
    except Exception:
        logger.exception(
            "Could not remove %s from workspace %s. It holds an installation token in "
            "plain text until the workspace is destroyed.",
            _SCRIPT_PATH,
            workspace.workspace_id,
        )
