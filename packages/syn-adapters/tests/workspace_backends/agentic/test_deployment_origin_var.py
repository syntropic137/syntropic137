"""The deployment must reach the exporter as its OWN variable, not as a tag.

Verified against the real binary in the pinned omni image rather than reasoned
about. `apss-session-exporter --json` reports:

    SESSION_STORE_ORIGIN_DEPLOYMENT set   -> "deployment":"syntropic137__development"
    deployment supplied only via tags     -> "deployment":null

The capability adapter maps AGENTIC_SESSION_STORE_DEPLOYMENT onto the
exporter's variable; it does not derive origin from tags. So a deployment sent
only as a tag arrives at the store unattributable, while syn137's own capture
indicator records the deployment it MEANT to send and looks entirely healthy.
That combination - broken attribution, healthy indicator - is why this is
asserted rather than left to the integration.
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.agentic.session_store_env import (
    TAG_DEPLOYMENT,
    apply_session_store_env,
    build_session_store_env,
)
from syn_shared.env_constants import (
    ENV_AGENTIC_SESSION_STORE_DEPLOYMENT,
    ENV_AGENTIC_SESSION_STORE_TAGS,
    SESSION_STORE_CONTRACT_ENV_VARS,
)
from syn_shared.settings.session_store import SessionStoreSettings

DEPLOYMENT = "syntropic137__development"
STORE = "https://sessions.example.com"


def _env(**kwargs: object) -> dict[str, str]:
    return build_session_store_env(
        SessionStoreSettings(url=STORE),
        execution_id="e-1",
        workspace_id="w-1",
        **kwargs,  # type: ignore[arg-type]
    )


class TestDeploymentReachesOrigin:
    @pytest.mark.unit
    def test_the_deployment_gets_its_own_variable(self) -> None:
        env = _env(deployment=DEPLOYMENT)

        assert env[ENV_AGENTIC_SESSION_STORE_DEPLOYMENT] == DEPLOYMENT

    @pytest.mark.unit
    def test_it_is_still_a_tag_as_well(self) -> None:
        """Tags are what the store FILTERS on.

        Dropping it there would trade one gap for another.
        """
        env = _env(deployment=DEPLOYMENT)

        assert f"{TAG_DEPLOYMENT}:{DEPLOYMENT}" in env[ENV_AGENTIC_SESSION_STORE_TAGS]

    @pytest.mark.unit
    def test_no_deployment_means_no_variable(self) -> None:
        """Better absent than empty: the exporter treats absence as unknown."""
        env = _env()

        assert ENV_AGENTIC_SESSION_STORE_DEPLOYMENT not in env

    @pytest.mark.unit
    def test_the_disabled_path_still_emits_nothing(self) -> None:
        env = build_session_store_env(
            SessionStoreSettings(url=None),
            execution_id="e-1",
            workspace_id="w-1",
            deployment=DEPLOYMENT,
        )

        assert env == {}


class TestTheVariableIsReserved:
    """A caller must not be able to restamp which deployment produced a session."""

    @pytest.mark.unit
    def test_it_is_part_of_the_contract_set(self) -> None:
        assert ENV_AGENTIC_SESSION_STORE_DEPLOYMENT in SESSION_STORE_CONTRACT_ENV_VARS

    @pytest.mark.unit
    def test_a_caller_supplied_value_is_overridden(self) -> None:
        applied = apply_session_store_env(
            {ENV_AGENTIC_SESSION_STORE_DEPLOYMENT: "someone-elses-deployment"},
            SessionStoreSettings(url=STORE),
            execution_id="e-1",
            workspace_id="w-1",
            deployment=DEPLOYMENT,
        )

        assert applied[ENV_AGENTIC_SESSION_STORE_DEPLOYMENT] == DEPLOYMENT

    @pytest.mark.unit
    def test_a_caller_cannot_smuggle_it_in_on_the_disabled_path(self) -> None:
        """Otherwise extra_environment could switch on attribution for a store
        that is not configured at all."""
        applied = apply_session_store_env(
            {ENV_AGENTIC_SESSION_STORE_DEPLOYMENT: "someone-elses-deployment"},
            SessionStoreSettings(url=None),
            execution_id="e-1",
            workspace_id="w-1",
        )

        assert ENV_AGENTIC_SESSION_STORE_DEPLOYMENT not in applied
