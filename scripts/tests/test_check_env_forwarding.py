"""Tests for the gate that keeps .env.example and the compose files in step.

The bug these exist for (#1101) is not visible at either end. `.env.example`
was correct, the Settings class was correct, and the API read the variable
correctly - the value was simply never handed across the one hop between them,
and every test that looked at either side passed. So these drive the hop: what
the published compose file actually names, and what the gate says about it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from scripts.check_env_forwarding import (
    HOST_ONLY,
    ApiEnvironment,
    api_service_of,
    deployment_stacks,
    documented_settings,
    stale_host_only,
    unforwarded,
)

pytestmark = pytest.mark.unit

PUBLISHED_COMPOSE = (
    Path(__file__).resolve().parents[2] / "docker" / "docker-compose.syntropic137.yaml"
)

#: The variable from the issue: set in a selfhost .env, restarted, no effect.
#: The operator's hand-fix was to add exactly this key to the api service.
ISSUE_1101_SETTING = "SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES"


def _published_api_environment() -> dict[str, object]:
    """Read the COMMITTED published file, not the generator's output.

    This is the file self-hosters download and run. Reading the generator here
    would test that the generator agrees with itself.
    """
    document = yaml.safe_load(PUBLISHED_COMPOSE.read_text())
    return document["services"]["api"]["environment"]


class TestThePublishedComposeSelfHostersRun:
    def test_it_names_the_switch_that_silently_did_nothing(self) -> None:
        assert ISSUE_1101_SETTING in _published_api_environment()

    def test_it_names_every_image_verification_setting_not_just_the_one_reported(
        self,
    ) -> None:
        """The reporter hit one. All seven had the same defect."""
        named = _published_api_environment()
        verify_settings = {s for s in documented_settings() if s.startswith("SYN_IMAGE_VERIFY_")}
        assert len(verify_settings) == 7
        assert verify_settings <= set(named)

    def test_the_forwarded_keys_carry_no_value(self) -> None:
        """A bare key, so an unset variable leaves the Settings default alone.

        `SYN_IMAGE_VERIFY_ENABLED: "false"` here would turn signature
        verification OFF for every self-hoster who never touched .env.
        """
        assert _published_api_environment()[ISSUE_1101_SETTING] is None


class TestEveryRealStack:
    """The whole-repository assertion. This is what fails without the fix."""

    @pytest.mark.parametrize("stack", deployment_stacks(), ids=lambda s: s.stack)
    def test_no_documented_setting_is_silently_dropped(self, stack: ApiEnvironment) -> None:
        assert unforwarded(stack, documented_settings()) == ()

    def test_dev_and_ondemand_are_exempt_only_because_they_forward_the_whole_env(
        self,
    ) -> None:
        """Their exemption has a precondition. Assert the precondition.

        If someone drops `env_file: ../.env` from one of these overlays, the
        per-name comparison starts applying to it - so this must be the reason
        they pass, not a coincidence.
        """
        by_name = {stack.stack: stack for stack in deployment_stacks()}
        assert by_name["dev"].forwards_operator_env_file
        assert by_name["ondemand"].forwards_operator_env_file
        assert not by_name["selfhost (published)"].forwards_operator_env_file


class TestTheHostOnlyList:
    def test_every_entry_carries_a_reason(self) -> None:
        assert all(entry.reason.strip() for entry in HOST_ONLY)

    def test_no_entry_names_something_that_is_not_a_setting(self) -> None:
        assert stale_host_only(documented_settings()) == ()

    def test_an_entry_naming_a_deleted_setting_is_reported(self) -> None:
        assert stale_host_only(frozenset({"APP_NAME"})) == tuple(
            sorted(entry.name for entry in HOST_ONLY)
        )


class TestTheRuleItself:
    """Driven with synthetic stacks, so each branch is exercised alone."""

    def test_a_curated_stack_reports_what_it_does_not_name(self) -> None:
        stack = ApiEnvironment.of("curated", {"environment": {"APP_NAME": "syn"}})
        assert unforwarded(stack, frozenset({"APP_NAME", "DEBUG"})) == ("DEBUG",)

    def test_a_stack_forwarding_the_operator_env_file_reports_nothing(self) -> None:
        stack = ApiEnvironment.of("catch-all", {"env_file": ["../.env"]})
        assert unforwarded(stack, frozenset({"APP_NAME", "DEBUG"})) == ()

    def test_an_unrelated_env_file_is_not_a_catch_all(self) -> None:
        """`.env.ondemand-foo` forwards a different file's contents."""
        stack = ApiEnvironment.of("partial", {"env_file": ["../.env.ondemand-x"]})
        assert unforwarded(stack, frozenset({"APP_NAME"})) == ("APP_NAME",)

    def test_a_host_only_setting_is_never_reported(self) -> None:
        stack = ApiEnvironment.of("curated", {"environment": {}})
        assert unforwarded(stack, frozenset({HOST_ONLY[0].name})) == ()

    def test_list_form_environment_is_read_the_same_as_dict_form(self) -> None:
        """The selfhost overlay uses list form; the base uses dict form."""
        as_list = ApiEnvironment.of("list", {"environment": ["APP_NAME=syn", "DEBUG"]})
        assert unforwarded(as_list, frozenset({"APP_NAME", "DEBUG"})) == ()

    def test_a_stack_naming_nothing_at_all_drops_everything(self) -> None:
        assert unforwarded(ApiEnvironment.of("empty", {}), frozenset({"APP_NAME"})) == ("APP_NAME",)


class TestReadingComposeFiles:
    def test_a_file_with_no_api_service_yields_an_empty_service(self) -> None:
        cloudflare = (
            Path(__file__).resolve().parents[2] / "docker" / "docker-compose.cloudflare.yaml"
        )
        assert api_service_of(cloudflare) == {}

    def test_the_base_compose_declares_the_api_service_this_gate_reads(self) -> None:
        base = Path(__file__).resolve().parents[2] / "docker" / "docker-compose.yaml"
        assert "environment" in api_service_of(base)
