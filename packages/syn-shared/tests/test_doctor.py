"""Tests for the configuration doctor.

The point of the doctor is provenance, so the cases that matter are the ones
where a name lives in more than one place. A vault value shadowed by a stale
``.env`` (and the reverse) is the confusion the command exists to end, and a
report that got the winner wrong would be worse than no report.
"""

from __future__ import annotations

import pytest

from syn_shared.doctor import (
    CaptureVerdict,
    EnvSources,
    Source,
    build_report,
    render,
    resolve_variable,
)
from syn_shared.settings.session_store import (
    ENV_SYN_SESSION_STORE_AUTH_TOKEN,
    ENV_SYN_SESSION_STORE_LABEL,
    ENV_SYN_SESSION_STORE_URL,
)

pytestmark = pytest.mark.unit

_NAME = "SYN_EXAMPLE"


def _sources(
    *,
    environ: dict[str, str] | None = None,
    dotenv: dict[str, str] | None = None,
    infra_dotenv: dict[str, str] | None = None,
    vault: dict[str, str] | None = None,
) -> EnvSources:
    return EnvSources(
        environ=environ or {},
        dotenv=dotenv or {},
        infra_dotenv=infra_dotenv or {},
        vault=vault,
    )


# ---------------------------------------------------------------------------
# Provenance: one source at a time
# ---------------------------------------------------------------------------


def test_unset_everywhere_reports_unset() -> None:
    result = resolve_variable(_NAME, _sources())
    assert result.source is Source.UNSET
    assert result.value is None


def test_default_is_reported_when_nothing_supplies_a_value() -> None:
    result = resolve_variable(_NAME, _sources(), default="7")
    assert result.source is Source.DEFAULT
    assert result.value == "7"


def test_environ_value_no_file_explains_is_shell() -> None:
    result = resolve_variable(_NAME, _sources(environ={_NAME: "from-shell"}))
    assert result.source is Source.SHELL
    assert result.value == "from-shell"


def test_environ_value_matching_dotenv_is_attributed_to_dotenv() -> None:
    """`just` sets dotenv-load, so .env reaches the process environment first."""
    result = resolve_variable(
        _NAME,
        _sources(environ={_NAME: "same"}, dotenv={_NAME: "same"}),
    )
    assert result.source is Source.DOTENV


def test_environ_value_matching_infra_dotenv_is_attributed_to_infra() -> None:
    result = resolve_variable(
        _NAME,
        _sources(environ={_NAME: "same"}, infra_dotenv={_NAME: "same"}),
    )
    assert result.source is Source.INFRA_DOTENV


def test_dotenv_only_wins_when_environment_is_empty() -> None:
    result = resolve_variable(_NAME, _sources(dotenv={_NAME: "from-file"}))
    assert result.source is Source.DOTENV
    assert result.value == "from-file"


def test_vault_only_is_reported_as_onepassword() -> None:
    result = resolve_variable(_NAME, _sources(vault={_NAME: "from-vault"}))
    assert result.source is Source.ONEPASSWORD
    assert result.value == "from-vault"


def test_empty_string_anywhere_is_treated_as_unset() -> None:
    """`SYN_SESSION_STORE_URL=` in a template must mean disabled, not enabled."""
    result = resolve_variable(_NAME, _sources(environ={_NAME: ""}, dotenv={_NAME: ""}))
    assert result.source is Source.UNSET
    assert result.value is None


# ---------------------------------------------------------------------------
# Provenance: contested names
# ---------------------------------------------------------------------------


def test_environment_beats_vault_and_the_vault_copy_is_reported_as_shadowed() -> None:
    """`inject_fields` writes a vault field only when os.environ lacks the name."""
    result = resolve_variable(
        _NAME,
        _sources(environ={_NAME: "from-shell"}, vault={_NAME: "from-vault"}),
    )
    assert result.source is Source.SHELL
    assert result.value == "from-shell"
    assert Source.ONEPASSWORD in result.shadowed


def test_value_in_both_dotenv_and_vault_env_wins_and_shadowing_is_reported() -> None:
    """The `just` case: dotenv-load puts .env in the environment, so .env wins.

    The vault copy is NOT injected (os.environ already holds the name), and it
    is reported so a stale file value is visible rather than mysterious.
    """
    result = resolve_variable(
        _NAME,
        _sources(
            environ={_NAME: "stale-from-file"},
            dotenv={_NAME: "stale-from-file"},
            vault={_NAME: "fresh-from-vault"},
        ),
    )
    assert result.source is Source.DOTENV
    assert result.value == "stale-from-file"
    assert Source.ONEPASSWORD in result.shadowed


def test_vault_beats_dotenv_when_the_process_environment_is_clean() -> None:
    """Outside `just` (the API container), .env never reaches os.environ.

    `resolve_op_secrets` injects the vault field, and pydantic reads os.environ
    before its ``env_file``. The vault therefore SHADOWS .env here, which is the
    opposite direction to the `just` case above.
    """
    result = resolve_variable(
        _NAME,
        _sources(dotenv={_NAME: "from-file"}, vault={_NAME: "from-vault"}),
    )
    assert result.source is Source.ONEPASSWORD
    assert result.value == "from-vault"
    assert Source.DOTENV in result.shadowed


def test_no_vault_lookup_means_vault_is_never_reported_as_a_source() -> None:
    sources = _sources(dotenv={_NAME: "from-file"}, vault=None)
    assert sources.vault_consulted is False
    assert resolve_variable(_NAME, sources).source is Source.DOTENV


# ---------------------------------------------------------------------------
# Session capture classification
# ---------------------------------------------------------------------------


def test_capture_off_when_no_url() -> None:
    report = build_report(_sources(environ={"APP_ENVIRONMENT": "development"}))
    assert report.capture is CaptureVerdict.OFF


def test_capture_warn_when_url_without_token() -> None:
    report = build_report(_sources(environ={ENV_SYN_SESSION_STORE_URL: "https://s.example.com"}))
    assert report.capture is CaptureVerdict.WARN


def test_capture_ok_when_url_and_token() -> None:
    report = build_report(
        _sources(
            environ={
                ENV_SYN_SESSION_STORE_URL: "https://s.example.com",
                ENV_SYN_SESSION_STORE_AUTH_TOKEN: "write-token",
            }
        )
    )
    assert report.capture is CaptureVerdict.OK


def test_warn_does_not_fail_the_command() -> None:
    report = build_report(_sources(environ={ENV_SYN_SESSION_STORE_URL: "https://s.example.com"}))
    assert report.exit_code == 0


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def test_usable_label_is_accepted() -> None:
    report = build_report(_sources(environ={ENV_SYN_SESSION_STORE_LABEL: "prod-west"}))
    assert report.label_declared is True
    assert report.label_usable is True
    assert "would be ignored" not in render(report, show_values=False)


def test_invalid_label_is_reported_as_ignored_without_echoing_it() -> None:
    bad = "prod:west"
    report = build_report(_sources(environ={ENV_SYN_SESSION_STORE_LABEL: bad}))
    assert report.label_declared is True
    assert report.label_usable is False
    text = render(report, show_values=False)
    assert "IGNORED" in text
    # A label that is not a usable identifier is probably not what the operator
    # believed they set, so the report must not echo it anywhere - that is how a
    # mis-pasted secret reaches the log this field exists to keep clean.
    assert bad not in text
    assert bad in render(report, show_values=True)


def test_overlong_label_is_unusable() -> None:
    report = build_report(_sources(environ={ENV_SYN_SESSION_STORE_LABEL: "a" * 65}))
    assert report.label_usable is False


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_secrets_are_redacted_by_default_including_the_url() -> None:
    url = "https://token@sessions.example.com/tenant"
    token = "super-secret-write-token"
    report = build_report(
        _sources(
            environ={
                ENV_SYN_SESSION_STORE_URL: url,
                ENV_SYN_SESSION_STORE_AUTH_TOKEN: token,
            }
        )
    )
    text = render(report, show_values=False)
    assert url not in text
    assert token not in text
    assert "(set, redacted)" in text


def test_show_values_prints_the_real_values() -> None:
    url = "https://sessions.example.com"
    report = build_report(_sources(environ={ENV_SYN_SESSION_STORE_URL: url}))
    assert url in render(report, show_values=True)


# ---------------------------------------------------------------------------
# Derived identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("app_env", "vault"),
    [
        ("selfhost", "syntropic137"),
        ("development", "syn137-dev"),
        ("production", "syn137-prod"),
        ("beta", "syn137-beta"),
        ("staging", "syn137-staging"),
    ],
)
def test_vault_is_derived_from_app_environment(app_env: str, vault: str) -> None:
    report = build_report(_sources(environ={"APP_ENVIRONMENT": app_env}))
    assert report.vault == vault
    assert report.deployment == f"syntropic137__{app_env}"


def test_environments_without_a_vault_report_none() -> None:
    report = build_report(_sources(environ={"APP_ENVIRONMENT": "test"}))
    assert report.vault is None
    assert report.deployment == "syntropic137__test"


def test_app_environment_defaults_to_development() -> None:
    report = build_report(_sources())
    assert report.app_environment.source is Source.DEFAULT
    assert report.vault == "syn137-dev"


def test_pinned_image_and_exporter_version_are_reported() -> None:
    report = build_report(_sources())
    assert report.image_ref.startswith("omni-agent-workspace@sha256:")
    assert report.exporter_version is not None
    assert report.exporter_version.count(".") == 2


def test_report_reads_the_collected_sources_not_the_ambient_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SessionStoreSettings` must not re-read os.environ behind the report.

    Every value is passed in explicitly and the env_file is disabled, so a
    variable set in the test runner's own environment cannot change the verdict.
    Without this, the doctor would report the machine it runs on rather than the
    sources it collected.
    """
    monkeypatch.setenv(ENV_SYN_SESSION_STORE_URL, "https://ambient.example.com")
    monkeypatch.setenv(ENV_SYN_SESSION_STORE_AUTH_TOKEN, "ambient-token")
    report = build_report(_sources())
    assert report.capture is CaptureVerdict.OFF


def test_a_value_that_only_reached_environ_from_dotenv_is_not_double_counted() -> None:
    """`.env  (also set in: .env)` is noise, not provenance."""
    result = resolve_variable(
        _NAME,
        _sources(environ={_NAME: "same"}, dotenv={_NAME: "same"}),
    )
    assert result.source is Source.DOTENV
    assert result.shadowed == ()


def test_shadowing_is_rendered_so_the_operator_can_see_the_losing_copy() -> None:
    report = build_report(
        _sources(
            environ={ENV_SYN_SESSION_STORE_URL: "https://shell.example.com"},
            dotenv={ENV_SYN_SESSION_STORE_URL: "https://file.example.com"},
        )
    )
    assert report.store_url.source is Source.SHELL
    assert Source.DOTENV in report.store_url.shadowed
    assert "also set in: .env - not used" in render(report, show_values=False)
