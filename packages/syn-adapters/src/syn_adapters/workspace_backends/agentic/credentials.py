"""The one `CredentialResolver` the workspace provider is constructed with.

agentic-workspace never takes a credential VALUE in a config or an operation
spec: it takes a `CredentialBinding` naming a ref, and resolves the ref at
launch through a resolver injected at construction. It then delivers the value
into the workload's environment only - never docker argv, labels, a spool or a
log line.

Syntropic137 holds two kinds of credential a workspace needs:

* the session-store write token, fixed for the provider's lifetime
  (`SESSION_STORE_AUTH_REF`, bound at workspace create);
* per-launch values such as the platform grant's API token (ADR-072), known
  only when a stream starts. `bind_launch` parks them under refs scoped to that
  one launch and `release` drops them once the provider has resolved them.

Anything else is refused, so injecting this resolver widens nothing.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from agentic_isolation.config import CredentialPolicyError, _reject_credential_environment
from agentic_isolation.contract import MISSING, CredentialBinding, CredentialRef
from agentic_isolation.contract._base import CredentialFreeStringMap
from pydantic import TypeAdapter, ValidationError

from syn_adapters.workspace_backends.agentic.session_store_env import SESSION_STORE_AUTH_REF

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_shared.settings.session_store import SessionStoreSettings

#: Scope of a credential that exists for one stream launch only.
LAUNCH_CREDENTIAL_SCOPE = "syn-launch"

# agentic-workspace's own rules for which environment keys name a credential.
# Asked, never re-derived: a copy here would drift the moment either pattern
# changes. Both are asked because they differ: the contract's map misses AUTH
# as a whole word (AGENTIC_SESSION_STORE_AUTH), which WorkspaceConfig's rule
# adds, and a key either one names must never travel as a plain value.
_CREDENTIAL_FREE = TypeAdapter(CredentialFreeStringMap)


def names_a_credential(key: str) -> bool:
    """Whether agentic-workspace refuses `key` as a plain environment entry."""
    try:
        _CREDENTIAL_FREE.validate_python({key: ""})
        _reject_credential_environment({key: ""})
    except (ValidationError, ValueError):
        return True
    return False


class WorkspaceCredentials:
    """Resolves the session-store token and launch-scoped credentials, nothing else."""

    def __init__(self, session_store: SessionStoreSettings) -> None:
        self._session_store = session_store
        self._launch: dict[str, str] = {}

    def bind_launch(
        self, environment: Mapping[str, str]
    ) -> tuple[dict[str, str], tuple[CredentialBinding, ...], tuple[str, ...]]:
        """Split `environment` into plain entries and credential bindings.

        Returns the credential-free environment, the bindings that replace the
        rest, and the ref names to pass to `release` once the operation has
        started.
        """
        plain: dict[str, str] = {}
        bindings: list[CredentialBinding] = []
        for key, value in environment.items():
            if not names_a_credential(key):
                plain[key] = value
                continue
            name = f"{key}.{uuid.uuid4().hex}"
            self._launch[name] = value
            bindings.append(
                CredentialBinding(
                    ref=CredentialRef(schema=MISSING, name=name, scope=LAUNCH_CREDENTIAL_SCOPE),
                    delivery="env",
                    target=key,
                )
            )
        return plain, tuple(bindings), tuple(b.ref.name for b in bindings)

    def release(self, names: tuple[str, ...]) -> None:
        """Forget launch-scoped values; the provider resolved them at start."""
        for name in names:
            self._launch.pop(name, None)

    async def resolve(self, ref: CredentialRef) -> str:
        if ref == SESSION_STORE_AUTH_REF:
            return self._session_store.auth_value
        if ref.scope == LAUNCH_CREDENTIAL_SCOPE and ref.name in self._launch:
            return self._launch[ref.name]
        raise CredentialPolicyError(
            f"credential {ref.name!r} (scope {ref.scope!r}) is not one Syntropic137 binds"
        )
