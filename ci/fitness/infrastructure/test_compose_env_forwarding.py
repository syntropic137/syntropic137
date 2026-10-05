"""A documented setting must take effect, or say that it will not (#1101).

`.env.example` is generated from the Settings classes, so every setting appears
there and looks available. The compose `environment:` block was written by hand,
and only what it names reaches the process. Nothing checked that the two agreed,
and they did not: 87 of 103 documented settings were inert. An operator set
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

import settings_forwarding
from settings_forwarding import (
    BASE_COMPOSE,
    COMPOSE_OWNED,
    ENV_EXAMPLE,
    FORWARD_WITH_DEFAULT,
    GENERATED_ENV,
    HANDWRITTEN_COMPOSE,
    NOT_FORWARDED,
    PUBLISHED_COMPOSE,
    _reaches_process,
    api_environment,
    base_extends_generated,
    documented_settings,
    generated_environment,
    generated_keys,
    handlisted,
    render_generated_env,
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


class TestGeneratedPassthrough:
    """New settings reach the container without anyone editing a compose file.

    The passthrough is generated into docker/generated/api.env.yaml, which the
    base api service `extends`. Compose files carry privilege and are
    owner-reviewed; the generated file is derived and is not. These pin the
    three ways that split could quietly stop holding.
    """

    def test_the_generated_file_is_not_stale(self) -> None:
        """`just gen-compose` and the committed file must agree.

        Without this, adding a setting to the Settings classes generates a line
        in `.env.example` and nothing in compose -- which is exactly how the two
        lists drifted apart in the first place.
        """
        assert GENERATED_ENV.is_file(), f"{GENERATED_ENV} is missing. Run: just gen-compose"
        assert render_generated_env() == GENERATED_ENV.read_text(), (
            f"{GENERATED_ENV.name} is stale. Run: just gen-compose"
        )

    def test_the_base_api_service_extends_it(self) -> None:
        """A generated file nothing references forwards nothing."""
        assert base_extends_generated(), (
            f"{BASE_COMPOSE.name}'s api service no longer `extends` "
            f"{GENERATED_ENV.name}, so no stack forwards the generated settings"
        )

    @pytest.mark.parametrize("path", HANDWRITTEN_COMPOSE, ids=lambda p: p.name)
    def test_no_compose_file_hand_lists_a_generated_setting(self, path: Path) -> None:
        """A second, hand-written source of truth is the drift this replaced."""
        problems = handlisted(path)
        assert not problems, "\n".join(problems)

    def test_the_hand_list_check_can_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative control: a base that restates a generated setting is caught."""
        name = generated_keys()[0]
        bad = tmp_path / "docker-compose.yaml"
        bad.write_text(
            BASE_COMPOSE.read_text().replace(
                "    environment:\n      SYN_API_PORT:",
                f"    environment:\n      {name}:\n      SYN_API_PORT:",
                1,
            )
        )
        monkeypatch.setattr(settings_forwarding, "BASE_COMPOSE", bad)
        assert handlisted(bad), f"restating {name} in the base went unnoticed"

    def test_the_overlay_check_flags_a_verbatim_copy_only(self, tmp_path: Path) -> None:
        """Overlays may override with their own value; copying ours is noise."""
        name = next(iter(FORWARD_WITH_DEFAULT))
        default = FORWARD_WITH_DEFAULT[name]
        copy = tmp_path / "docker-compose.copy.yaml"
        copy.write_text(
            f"services:\n  api:\n    environment:\n      {name}: ${{{name}:-{default}}}\n"
        )
        override = tmp_path / "docker-compose.override.yaml"
        override.write_text(f"services:\n  api:\n    environment:\n      {name}: fixed\n")
        assert handlisted(copy)
        assert not handlisted(override)

    def test_a_new_setting_needs_no_compose_edit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The point of the split, as a dry run.

        A setting added to a Settings class reaches .env.example (just gen-env);
        from there the generated file gains it and nothing else changes. The
        compose files are read, never rendered, by the generator.
        """
        new = "SYN_THROWAWAY_PROBE_SETTING"
        real = documented_settings()
        monkeypatch.setattr(settings_forwarding, "documented_settings", lambda: [*real, new])
        before = {path: path.read_text() for path in HANDWRITTEN_COMPOSE}

        rendered = render_generated_env()

        assert f"      {new}:\n" in rendered
        assert {path: path.read_text() for path in HANDWRITTEN_COMPOSE} == before

    def test_defaults_and_ownership_name_real_generated_settings(self) -> None:
        """A stale table entry would promise a form the file no longer has."""
        keys = set(generated_keys())
        assert not set(FORWARD_WITH_DEFAULT) - keys, (
            "FORWARD_WITH_DEFAULT names a non-generated key"
        )
        assert not set(COMPOSE_OWNED) & keys, "COMPOSE_OWNED keys must not also be generated"
        assert not set(COMPOSE_OWNED) - set(documented_settings()), (
            "COMPOSE_OWNED names an unknown setting"
        )
        env = generated_environment()
        for name, default in FORWARD_WITH_DEFAULT.items():
            assert env[name] == "${" + name + ":-" + default + "}"


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
