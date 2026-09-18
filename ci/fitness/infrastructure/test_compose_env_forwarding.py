"""A documented setting must take effect, or say that it will not (#1101).

`.env.example` is generated from the Settings classes, so every setting appears
there and looks available. The compose `environment:` block was written by hand,
and only what it names reaches the process. Nothing checked that the two agreed,
and they did not: 76 of 103 documented settings were inert. An operator set
`SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES=true` on a selfhost, restarted, and got the
old behaviour -- no error, no warning, and a confusing signature failure from the
very switch that appeared to be on.

The bad half of that is the silence. A setting the deployment cannot honour is
allowed to exist; being ignored without a word is not. So this pins both halves:
every documented setting either reaches the API process, or carries a reason in
`NOT_FORWARDED` that `.env.example` prints beside it.

Asserted against `docker-compose.syntropic137.yaml` because that is the file a
self-hoster downloads and runs -- the deployment the bug was reported against.
It is generated from the base plus the selfhost overlay, so checking it covers
both without re-implementing the merge.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from settings_forwarding import (
    BASE_COMPOSE,
    BEGIN_MARKER,
    END_MARKER,
    ENV_EXAMPLE,
    NOT_FORWARDED,
    PUBLISHED_COMPOSE,
    _reaches_process,
    api_environment,
    documented_settings,
    render_base_compose,
    report,
)

# `architecture` is what `just fitness-invariants` (inside `just preflight`)
# selects; `unit` is what the PR-gating unit job selects. Both, deliberately:
# the check is static and costs milliseconds, and a gate collected by only one
# job is a gate that a change to that job silently switches off.
pytestmark = [pytest.mark.unit, pytest.mark.architecture]


def test_every_documented_setting_is_honoured_or_refused_in_writing() -> None:
    """The whole invariant, in one assertion.

    Fails three ways, each the same defect: a setting that reaches nothing, a
    setting the compose file overrides with a fixed value, and a refusal left
    behind after the setting started working again.
    """
    failures = report().failures()
    assert not failures, "\n".join(["settings and compose disagree:", *failures])


def test_the_reported_switch_reaches_the_container() -> None:
    """The named regression: #1101's setting, in the file the operator runs."""
    env = api_environment(PUBLISHED_COMPOSE.read_text())
    name = "SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES"
    assert name in env, (
        f"{name} is absent from the api environment, so setting it in .env does nothing"
    )
    assert _reaches_process(name, env[name]), (
        f"{name} is present but pinned to {env[name]!r}, so the operator's value is still discarded"
    )


def test_the_generated_block_is_not_stale() -> None:
    """`just gen-compose` and the committed base must agree.

    Without this, adding a setting to the Settings classes generates a line in
    `.env.example` and nothing in compose -- which is exactly how the two lists
    drifted apart in the first place.
    """
    committed = BASE_COMPOSE.read_text()
    assert BEGIN_MARKER in committed and END_MARKER in committed, (
        "the generated-block markers are gone from docker-compose.yaml; "
        "nothing regenerates the forwarding list any more"
    )
    assert render_base_compose() == committed, "docker-compose.yaml is stale. Run: just gen-compose"


class TestRefusalsAreVisibleToOperators:
    """A refusal only helps where the operator looks, which is `.env.example`."""

    def test_every_refusal_is_printed_beside_its_setting(self) -> None:
        example = ENV_EXAMPLE.read_text()
        missing = [
            name for name in NOT_FORWARDED if "IGNORED IN .env" not in _stanza_for(example, name)
        ]
        assert not missing, (
            f"{missing}: not forwarded, and .env.example does not say so. Run: just gen-env"
        )

    def test_every_refusal_names_a_setting_that_still_exists(self) -> None:
        unknown = sorted(set(NOT_FORWARDED) - set(documented_settings()))
        assert not unknown, f"{unknown}: refused, but no longer documented in .env.example"

    @pytest.mark.parametrize("name", sorted(NOT_FORWARDED))
    def test_a_refusal_gives_a_reason(self, name: str) -> None:
        """An empty or one-word reason is an exemption wearing a reason's clothes."""
        reason = NOT_FORWARDED[name]
        assert len(reason.split()) >= 5, f"{name}: {reason!r} does not explain anything"


class TestPinsAreNotMistakenForForwarding:
    """The hop where this gate could go green while the setting stays inert.

    A compose value that interpolates a DIFFERENT variable reads like
    forwarding -- `SYN_STORAGE_MINIO_ACCESS_KEY: ${MINIO_ROOT_USER:-minioadmin}`
    has the operator's key nowhere in it. "The value contains `${`" would count
    it as forwarded and this whole file would pass while the setting did
    nothing, which is #1101 reproduced inside its own check.
    """

    @pytest.mark.parametrize(
        ("label", "value"),
        [
            ("bare passthrough", None),
            ("plain interpolation", "${FOO}"),
            ("interpolation with default", "${FOO:-fallback}"),
            ("interpolation with empty default", "${FOO:-}"),
            ("interpolation with unset-only default", "${FOO-fallback}"),
        ],
    )
    def test_reaches_the_process(self, label: str, value: str | None) -> None:
        assert _reaches_process("FOO", value), label

    @pytest.mark.parametrize(
        ("label", "value"),
        [
            ("fixed literal", "event-store"),
            ("another variable", "${BAR:-fallback}"),
            ("another variable, name-prefixed", "${FOO_OTHER:-x}"),
            ("this variable only inside a longer name", "${MY_FOO}"),
            ("empty string", ""),
        ],
    )
    def test_does_not_reach_the_process(self, label: str, value: str) -> None:
        assert not _reaches_process("FOO", value), label


def _stanza_for(env_example: str, name: str) -> str:
    """The comment block immediately above `name=` in `.env.example`."""
    lines = env_example.splitlines()
    index = next((i for i, line in enumerate(lines) if line.startswith(f"{name}=")), None)
    assert index is not None, f"{name} is not in .env.example"
    start = index
    while start > 0 and lines[start - 1].startswith("#"):
        start -= 1
    return "\n".join(lines[start:index])
