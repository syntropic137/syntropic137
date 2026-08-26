"""Tests for the configuration doctor.

The point of the doctor is provenance, so the cases that matter are the ones
where a name lives in more than one place. A vault value shadowed by a stale
``.env`` (and the reverse) is the confusion the command exists to end, and a
report that got the winner wrong would be worse than no report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from syn_shared.doctor import (
    CaptureVerdict,
    EnvSources,
    Source,
    _load_vault,
    build_report,
    collect_sources,
    main,
    render,
    resolve_variable,
    resolver_tier,
)
from syn_shared.settings.session_store import (
    ENV_SYN_SESSION_STORE_AUTH_TOKEN,
    ENV_SYN_SESSION_STORE_LABEL,
    ENV_SYN_SESSION_STORE_URL,
    SessionStoreSettings,
    usable_label,
)
from syn_shared.settings.workspace_images import (
    PINNED_DIGESTS,
    PINNED_EXPORTER_VERSIONS,
    WorkspaceImageProvider,
    workspace_image_name,
)

if TYPE_CHECKING:
    from pathlib import Path

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
    # A shell export of the same bytes is indistinguishable, so the report must
    # not claim certainty it does not have.
    assert result.inferred is True


def test_shell_value_no_file_matches_is_not_inferred() -> None:
    result = resolve_variable(
        _NAME,
        _sources(environ={_NAME: "from-shell"}, dotenv={_NAME: "other"}),
    )
    assert result.source is Source.SHELL
    assert result.inferred is False


def test_a_vault_value_equal_to_the_environment_is_not_credited_with_supplying_it() -> None:
    """The doctor never calls `resolve_op_secrets`, so no vault field is in os.environ.

    Crediting 1Password on a value match would name a source that did nothing
    and would drop the real one from the report.
    """
    result = resolve_variable(
        _NAME,
        _sources(environ={_NAME: "same"}, vault={_NAME: "same"}),
    )
    assert result.source is Source.SHELL
    assert Source.ONEPASSWORD in result.shadowed


def test_infra_dotenv_never_explains_the_environment() -> None:
    """`just` loads the root .env only; infra/.env is not exported to a recipe.

    Attributing the value to infra/.env would send an operator to edit a file
    that has no effect on it.
    """
    result = resolve_variable(
        _NAME,
        _sources(environ={_NAME: "same"}, infra_dotenv={_NAME: "same"}),
    )
    assert result.source is Source.SHELL
    assert result.inert == (Source.INFRA_DOTENV,)
    assert Source.INFRA_DOTENV not in result.shadowed


def test_infra_dotenv_alone_can_never_be_the_effective_value() -> None:
    """No Settings class lists infra/.env as an env_file.

    Letting it win would report session capture as ON for an operator whose only
    copy of the URL sits in a file the API never opens.
    """
    report = build_report(_sources(infra_dotenv={ENV_SYN_SESSION_STORE_URL: "https://x.test"}))
    assert report.capture is CaptureVerdict.OFF
    assert report.store_url.source is Source.UNSET
    assert report.store_url.inert == (Source.INFRA_DOTENV,)
    assert "never read on this path" in render(report, show_values=False)


def test_dotenv_only_wins_when_environment_is_empty() -> None:
    result = resolve_variable(_NAME, _sources(dotenv={_NAME: "from-file"}))
    assert result.source is Source.DOTENV
    assert result.value == "from-file"


def test_vault_only_is_reported_as_onepassword() -> None:
    result = resolve_variable(_NAME, _sources(vault={_NAME: "from-vault"}))
    assert result.source is Source.ONEPASSWORD
    assert result.value == "from-vault"


def test_empty_string_everywhere_is_treated_as_unset() -> None:
    """`SYN_SESSION_STORE_URL=` in a template must mean disabled, not enabled."""
    result = resolve_variable(_NAME, _sources(environ={_NAME: ""}, dotenv={_NAME: ""}))
    assert result.source is Source.UNSET
    assert result.value is None


def test_an_empty_environment_value_beats_a_populated_dotenv() -> None:
    """`SYN_SESSION_STORE_URL= just doctor` turns capture OFF, and must report OFF.

    pydantic reads os.environ before it opens its env_file, so the empty string
    is what the settings see. Reporting the .env line as the winner would tell
    an operator capture is ON immediately after they turned it off.
    """
    result = resolve_variable(_NAME, _sources(environ={_NAME: ""}, dotenv={_NAME: "from-file"}))
    assert result.empty_override is True
    assert result.source is Source.SHELL
    assert result.inferred is False
    assert result.value is None
    assert result.is_set is False
    assert result.shadowed == (Source.DOTENV,)


def test_the_vault_replaces_an_empty_environment_value() -> None:
    """`inject_fields` guards on `not os.environ.get(label)`, so "" counts as absent."""
    result = resolve_variable(_NAME, _sources(environ={_NAME: ""}, vault={_NAME: "from-vault"}))
    assert result.source is Source.ONEPASSWORD
    assert result.value == "from-vault"
    assert result.empty_override is False


def test_an_emptied_url_reports_capture_off_and_says_so_in_the_output() -> None:
    report = build_report(
        _sources(
            environ={ENV_SYN_SESSION_STORE_URL: ""},
            dotenv={ENV_SYN_SESSION_STORE_URL: "https://file.example.com"},
        )
    )
    assert report.capture is CaptureVerdict.OFF
    assert "overrides every file" in render(report, show_values=False)


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
    text = render(report, show_values=False)
    # Assert against the string the code actually emits. "would be ignored"
    # appears nowhere in the module, so the old assertion held whether or not
    # the warning was rendered.
    assert "IGNORED" not in text
    assert "prod-west" in text


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


def test_app_environment_defaults_to_development_but_names_no_vault() -> None:
    """`resolve_op_secrets` returns before it looks a vault up when the tier is unset.

    The deployment identity still defaults, because `AppEnvironment` really does
    fall back to development and that is what gets stamped on a session. The
    vault does not, because naming syn137-dev would advertise an association the
    runtime never makes - and the report would then say "syn137-dev" and
    "1Password not consulted" on consecutive lines.
    """
    report = build_report(_sources())
    assert report.app_environment.source is Source.DEFAULT
    assert report.vault is None
    assert report.deployment == "syntropic137__development"
    assert "APP_ENVIRONMENT is unset" in render(report, show_values=False)


def test_resolver_tier_is_empty_when_app_environment_is_unset() -> None:
    assert resolver_tier(_sources()) == ""
    assert resolver_tier(_sources(environ={"APP_ENVIRONMENT": "Selfhost"})) == "selfhost"
    assert resolver_tier(_sources(dotenv={"APP_ENVIRONMENT": "beta"})) == "beta"


def test_an_emptied_app_environment_names_no_vault_either() -> None:
    """The resolver skips on a blank APP_ENVIRONMENT even when .env has one."""
    sources = _sources(environ={"APP_ENVIRONMENT": ""}, dotenv={"APP_ENVIRONMENT": "production"})
    assert resolver_tier(sources) == ""
    assert build_report(sources).vault is None


def test_pinned_image_and_exporter_version_are_reported() -> None:
    """Exact, not "some dotted string".

    The version used to be recovered by searching the pin's prose, which keeps
    previous pins on purpose - so a loose assertion passed while the report
    named a historical exporter.
    """
    report = build_report(_sources())
    assert report.image_ref == (
        f"{workspace_image_name(WorkspaceImageProvider.OMNI_AGENT)}"
        f"@{PINNED_DIGESTS[WorkspaceImageProvider.OMNI_AGENT]}"
    )
    assert report.exporter_version == PINNED_EXPORTER_VERSIONS[WorkspaceImageProvider.OMNI_AGENT]


def test_every_pinned_exporter_version_belongs_to_a_pinned_image() -> None:
    """A version recorded for an image that is no longer pinned describes nothing."""
    assert set(PINNED_EXPORTER_VERSIONS) <= set(PINNED_DIGESTS)


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


# ---------------------------------------------------------------------------
# Vault reading
# ---------------------------------------------------------------------------


def test_a_duplicated_vault_label_resolves_the_way_inject_fields_would(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`inject_fields` never overwrites a label it already wrote, so the FIRST wins.

    A dict comprehension here would take the last, and the doctor would then
    name a value the running process never received - the exact failure this
    command exists to prevent.
    """
    item = {
        "fields": [
            {"label": "DUPED", "value": ""},
            {"label": "DUPED", "value": "first-nonempty"},
            {"label": "DUPED", "value": "second-nonempty"},
            {"label": "  SPACED  ", "value": "trimmed"},
            {"label": "", "value": "unlabelled"},
        ]
    }
    monkeypatch.setattr("syn_shared.doctor.op_available", lambda: True)
    monkeypatch.setattr("syn_shared.doctor.fetch_op_item", lambda _vault, _title: item)

    vault = _load_vault("development")
    assert vault == {"DUPED": "first-nonempty", "SPACED": "trimmed"}


def test_no_vault_is_read_when_app_environment_names_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "syn_shared.doctor.op_available",
        lambda: pytest.fail("op must not be consulted for an unmapped environment"),
    )
    assert _load_vault("") is None
    assert _load_vault("test") is None


# ---------------------------------------------------------------------------
# The command boundary
#
# Everything above tests pure functions. These tests exist because the pure
# functions being right is not the same claim as `just doctor` being right:
# argument parsing, file reading and the exit code are what an operator and a
# CI job actually meet.
# ---------------------------------------------------------------------------


def _write_repo(root: Path, *, dotenv: str = "", infra_dotenv: str = "") -> Path:
    (root / "infra").mkdir(parents=True, exist_ok=True)
    (root / ".env").write_text(dotenv, encoding="utf-8")
    (root / "infra" / ".env").write_text(infra_dotenv, encoding="utf-8")
    return root


def test_collect_sources_reads_both_env_files_and_skips_the_vault_when_asked(
    tmp_path: Path,
) -> None:
    root = _write_repo(
        tmp_path,
        dotenv="APP_ENVIRONMENT=selfhost\nSYN_SESSION_STORE_LABEL=mac-mini\n",
        infra_dotenv="SYN_SESSION_STORE_AUTH_TOKEN=inert\n",
    )
    sources = collect_sources(root, consult_vault=False)
    assert sources.dotenv["SYN_SESSION_STORE_LABEL"] == "mac-mini"
    assert sources.infra_dotenv[ENV_SYN_SESSION_STORE_AUTH_TOKEN] == "inert"
    assert sources.vault_consulted is False


def test_collect_sources_survives_a_repo_with_no_env_files(tmp_path: Path) -> None:
    """A diagnostic that dies on a fresh clone is useless exactly when it is needed."""
    sources = collect_sources(tmp_path, consult_vault=False)
    assert sources.dotenv == {}
    assert sources.infra_dotenv == {}


def test_collect_sources_selects_the_vault_from_the_files_it_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tier that picks the vault comes from the same resolution as the report."""
    asked: list[str] = []
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    monkeypatch.setattr("syn_shared.doctor.op_available", lambda: True)
    monkeypatch.setattr(
        "syn_shared.doctor.fetch_op_item",
        lambda vault, _title: asked.append(vault) or {"fields": []},
    )
    root = _write_repo(tmp_path, dotenv="APP_ENVIRONMENT=production\n")
    collect_sources(root)
    assert asked == ["syn137-prod"]


def test_main_prints_the_report_and_exits_zero_when_capture_is_off(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_repo(tmp_path, dotenv="APP_ENVIRONMENT=selfhost\n")
    code = main(["--no-1password", "--repo-root", str(tmp_path)])
    assert code == 0
    assert "Syntropic137 configuration doctor" in capsys.readouterr().out


def test_main_exits_zero_on_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """WARN must never fail the command - capture-off is a legitimate posture.

    Asserted through main(), not through the report property, so an exit-code
    regression in the command itself is caught.
    """
    monkeypatch.setenv(ENV_SYN_SESSION_STORE_URL, "https://s.example.com")
    monkeypatch.delenv(ENV_SYN_SESSION_STORE_AUTH_TOKEN, raising=False)
    _write_repo(tmp_path, dotenv="APP_ENVIRONMENT=selfhost\n")
    assert main(["--no-1password", "--repo-root", str(tmp_path)]) == 0
    assert "Session capture: WARN" in capsys.readouterr().out


def test_main_exits_one_on_an_unusable_app_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings would reject this at startup, so nothing runs with it."""
    monkeypatch.setenv("APP_ENVIRONMENT", "prodution")
    _write_repo(tmp_path)
    assert main(["--no-1password", "--repo-root", str(tmp_path)]) == 1
    assert "not a known environment" in capsys.readouterr().out


def test_main_redacts_secrets_by_default_and_prints_them_only_when_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redaction has to hold through argument parsing, not just through render()."""
    url = "https://token@sessions.example.com/tenant"
    monkeypatch.setenv(ENV_SYN_SESSION_STORE_URL, url)
    _write_repo(tmp_path, dotenv="APP_ENVIRONMENT=selfhost\n")

    assert main(["--no-1password", "--repo-root", str(tmp_path)]) == 0
    assert url not in capsys.readouterr().out

    assert main(["--no-1password", "--repo-root", str(tmp_path), "--show-values"]) == 0
    assert url in capsys.readouterr().out


def test_main_never_consults_1password_with_the_offline_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "syn_shared.doctor.op_available",
        lambda: pytest.fail("--no-1password must not reach op"),
    )
    _write_repo(tmp_path, dotenv="APP_ENVIRONMENT=production\n")
    assert main(["--no-1password", "--repo-root", str(tmp_path)]) == 0


def test_main_rejects_an_unknown_flag_with_the_argparse_convention(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--not-a-flag"])
    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------------


def test_the_inferred_legend_appears_only_when_something_is_inferred() -> None:
    inferred = build_report(
        _sources(
            environ={ENV_SYN_SESSION_STORE_LABEL: "same"},
            dotenv={ENV_SYN_SESSION_STORE_LABEL: "same"},
        )
    )
    assert "inferred" in render(inferred, show_values=False)
    assert "matched by value, not observed" in render(inferred, show_values=False)

    certain = build_report(_sources(environ={ENV_SYN_SESSION_STORE_LABEL: "only-shell"}))
    assert "matched by value, not observed" not in render(certain, show_values=False)


def test_the_inert_legend_appears_only_when_something_is_inert() -> None:
    inert = build_report(_sources(infra_dotenv={ENV_SYN_SESSION_STORE_URL: "https://x.test"}))
    assert "is not the env_file of any Settings class" in render(inert, show_values=False)

    clean = build_report(_sources())
    assert "is not the env_file of any Settings class" not in render(clean, show_values=False)


def test_an_empty_infra_declaration_is_still_reported() -> None:
    """`NAME=` is a line an operator can see and reasonably expect to matter."""
    result = resolve_variable(_NAME, _sources(infra_dotenv={_NAME: ""}))
    assert result.inert == (Source.INFRA_DOTENV,)


# ---------------------------------------------------------------------------
# Settings the application itself refuses
#
# `SessionStoreSettings` rejects a URL with whitespace inside it (a pasted line
# break cannot be guessed away). The doctor is therefore handed values that
# raise on construction - on exactly the misconfiguration it exists to
# diagnose, which is the one moment it most needs to keep talking.
# ---------------------------------------------------------------------------

_PASTED_URL = "http://host:18090 /v1/sessions/batch"


def test_a_url_the_settings_reject_is_reported_not_raised() -> None:
    report = build_report(_sources(environ={ENV_SYN_SESSION_STORE_URL: _PASTED_URL}))
    assert report.capture is CaptureVerdict.INVALID
    assert report.rejected_names == (ENV_SYN_SESSION_STORE_URL,)


def test_a_rejected_value_is_not_echoed_by_default() -> None:
    """A value that failed validation is the likeliest of all to be a mis-paste.

    "By default" is the accurate claim: `--show-values` prints it, which is that
    flag's whole contract. The name used to say "never", which the flag
    contradicts.
    """
    report = build_report(_sources(environ={ENV_SYN_SESSION_STORE_URL: _PASTED_URL}))
    text = render(report, show_values=False)
    assert _PASTED_URL not in text
    # Findings are wrapped to the report width, so match on the unwrapped text.
    assert "was rejected as malformed" in " ".join(text.split())


def test_an_unbuildable_configuration_fails_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API would not start with this, so the doctor must not exit 0."""
    monkeypatch.setenv(ENV_SYN_SESSION_STORE_URL, _PASTED_URL)
    _write_repo(tmp_path, dotenv="APP_ENVIRONMENT=selfhost\n")
    assert main(["--no-1password", "--repo-root", str(tmp_path)]) == 1


def test_invalid_is_distinct_from_off() -> None:
    """OFF is a working system with capture disabled; INVALID will not start."""
    off = build_report(_sources())
    assert off.capture is CaptureVerdict.OFF
    assert off.rejected_names == ()
    assert off.exit_code == 0


def test_the_settings_do_not_leak_a_rejected_url_into_their_own_error() -> None:
    """Pydantic embeds the offending input by default, and this URL is secret.

    Guarded here because the leak reaches the API startup log too, not only
    this command - the posture line logs no part of the URL for the same
    reason.
    """
    with pytest.raises(ValidationError) as excinfo:
        SessionStoreSettings(url=_PASTED_URL, _env_file=None)  # pyright: ignore[reportCallIssue]
    assert "host:18090" not in str(excinfo.value)


def test_a_malformed_label_is_withheld_even_when_the_url_is_rejected() -> None:
    """A bad URL must not take the label rule down with it.

    The label rule exists to catch a value that is not what the operator thinks
    they set, which is the case likeliest to be a mis-pasted credential. Gating
    it on the whole settings object building meant one malformed URL printed the
    label verbatim in default, redacted output.
    """
    pasted_secret = "sk-live-accident/credential"
    report = build_report(
        _sources(
            environ={
                ENV_SYN_SESSION_STORE_URL: _PASTED_URL,
                ENV_SYN_SESSION_STORE_LABEL: pasted_secret,
            }
        )
    )
    assert report.capture is CaptureVerdict.INVALID
    assert report.label_usable is False
    assert pasted_secret not in render(report, show_values=False)


def test_a_usable_label_survives_a_rejected_url() -> None:
    """`label_usable` describes the LABEL, not whether some other field parsed."""
    report = build_report(
        _sources(
            environ={
                ENV_SYN_SESSION_STORE_URL: _PASTED_URL,
                ENV_SYN_SESSION_STORE_LABEL: "mac-mini",
            }
        )
    )
    assert report.capture is CaptureVerdict.INVALID
    assert report.label_usable is True
    assert "mac-mini" in render(report, show_values=False)


def test_the_label_rule_has_one_definition() -> None:
    """`display_label` delegates to `usable_label`, so they cannot drift."""
    for candidate in ("mac-mini", "prod:west", "", "a" * 65, "  spaced  "):
        settings = SessionStoreSettings(label=candidate, _env_file=None)  # pyright: ignore[reportCallIssue]
        assert settings.display_label == usable_label(candidate)
