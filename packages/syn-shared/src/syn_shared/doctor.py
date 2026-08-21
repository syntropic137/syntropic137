"""Configuration health report with provenance ("where did this value come from?").

Motivation
----------
Syntropic137 reads configuration from four places that overlap: the shell
environment, the repo-root ``.env``, ``infra/.env`` and a 1Password vault item.
Nothing told an operator which of them supplied the value a process actually
used, and nothing mentioned session capture at all - ``_env-check`` never names
it, and the ``--1password`` summary loops a hardcoded list of ten variables that
omits both session-store variables, so it reports "complete" while silently
skipping them.

This module answers two questions for each variable it knows about: what is the
EFFECTIVE value, and which source WON. When several sources hold a name, the
losers are reported too - a value shadowed by a stale file is exactly the
confusion this exists to end.

Resolution order (verified against the code, not assumed)
---------------------------------------------------------
1. ``os.environ`` - pydantic-settings reads the process environment before it
   reads any ``env_file``.
2. 1Password - ``op_client.inject_fields`` writes a vault field into
   ``os.environ`` only ``if ... not os.environ.get(label)``, so anything already
   in the environment beats the vault.
3. repo-root ``.env`` - the ``env_file`` of every settings class.
4. the pydantic field default.

``infra/.env`` is NOT read by the pydantic ``Settings`` classes (see
``InfraSettings``); it reaches recipes through ``scripts/resolve_infra_env.py``.
It is reported for completeness and flagged as file-only.

A caveat this report is explicit about: the justfile sets ``dotenv-load``, so
under ``just doctor`` the root ``.env`` has ALREADY been merged into the process
environment. A name is therefore attributed to ``.env`` when the environment
value equals the file value, and to ``shell`` only when the environment holds a
value no file explains.

Redaction
---------
Secret values are never printed. ``SYN_SESSION_STORE_URL`` counts as secret:
its own field docstring notes that every part of a URL is operator-supplied and
could carry a credential, which is why the startup posture line logs no part of
it. ``--show-values`` opts out, deliberately, per invocation.
"""

from __future__ import annotations

import argparse
import inspect
import os
import re
import sys
import textwrap
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from syn_shared.env_constants import ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES
from syn_shared.settings.env_file import parse_env_file
from syn_shared.settings.op_client import fetch_op_item, op_available
from syn_shared.settings.op_resolver import _ENV_TO_VAULT, _OP_ITEM_TITLE
from syn_shared.settings.session_store import (
    ENV_SYN_SESSION_STORE_AUTH_TOKEN,
    ENV_SYN_SESSION_STORE_LABEL,
    ENV_SYN_SESSION_STORE_URL,
    SessionStoreSettings,
)
from syn_shared.settings.workspace_images import (
    PINNED_DIGESTS,
    WorkspaceImageProvider,
    workspace_image_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "CaptureVerdict",
    "DoctorReport",
    "Severity",
    "Source",
    "VariableReport",
    "build_report",
    "classify_capture",
    "main",
    "render",
    "resolve_variable",
]

ENV_APP_ENVIRONMENT = "APP_ENVIRONMENT"

# An environment absent from ``_ENV_TO_VAULT`` (test, offline, anything
# mistyped) is reported as "no vault" rather than as the justfile summary's
# ``syn137-dev`` fallback, which would name a vault that tier never reads.

#: ``syntropic137__<tier>`` - kept in step with
#: ``syn_adapters...session_store_env.deployment_identity``, which syn-adapters
#: owns. Restated here rather than imported because syn-shared must not depend
#: on syn-adapters.
_DEPLOYMENT_SOURCE = "syntropic137"
_DEPLOYMENT_SEPARATOR = "__"

#: Names whose VALUES must never be printed unless --show-values is given.
_SECRET_NAMES: frozenset[str] = frozenset(
    {
        ENV_SYN_SESSION_STORE_AUTH_TOKEN,
        # Sensitive on purpose: see the module docstring.
        ENV_SYN_SESSION_STORE_URL,
    }
)

_EXPORTER_VERSION = re.compile(r"apss-session-exporter (\d+\.\d+\.\d+)")


class Source(StrEnum):
    """Where an effective value came from."""

    SHELL = "shell"
    DOTENV = ".env"
    INFRA_DOTENV = "infra/.env"
    ONEPASSWORD = "1Password"
    DEFAULT = "default"
    UNSET = "unset"


class Severity(StrEnum):
    """How loudly a finding should be reported. Only ERROR fails the command."""

    OK = "ok"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class CaptureVerdict(StrEnum):
    """Session-capture configuration posture."""

    OFF = "OFF"
    WARN = "WARN"
    OK = "OK"


@dataclass(frozen=True, slots=True)
class EnvSources:
    """The candidate values each source holds, before precedence is applied.

    ``vault`` is ``None`` when 1Password was not consulted (``op`` missing, not
    authenticated, unreachable, or an environment with no vault mapping). That
    is distinct from an empty mapping, which means "consulted, held nothing".
    """

    environ: Mapping[str, str]
    dotenv: Mapping[str, str]
    infra_dotenv: Mapping[str, str]
    vault: Mapping[str, str] | None

    @property
    def vault_consulted(self) -> bool:
        return self.vault is not None


@dataclass(frozen=True, slots=True)
class VariableReport:
    """One variable: its effective value, which source won, and who else holds it."""

    name: str
    source: Source
    value: str | None
    is_secret: bool
    #: Sources that also hold this name but lost. Reported so a shadowed value
    #: is visible rather than mysterious.
    shadowed: tuple[Source, ...]
    #: Set for a non-secret value that still must not be echoed - see
    #: ``withheld_note``. Independent of ``is_secret`` so the reason survives.
    withhold: bool = False
    withheld_note: str = "(set, value withheld)"

    @property
    def is_set(self) -> bool:
        return self.value is not None and self.value != ""

    def display_value(self, *, show_values: bool) -> str:
        if not self.is_set:
            return "(unset)"
        if self.withhold and not show_values:
            return self.withheld_note
        if self.is_secret and not show_values:
            return "(set, redacted)"
        return self.value or ""


@dataclass(frozen=True, slots=True)
class Finding:
    """A single rendered line with a severity."""

    severity: Severity
    text: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Everything the command found, ready to render."""

    app_environment: VariableReport
    #: None when this APP_ENVIRONMENT maps to no vault at all.
    vault: str | None
    vault_consulted: bool
    deployment: str
    store_url: VariableReport
    store_token: VariableReport
    store_label: VariableReport
    capture: CaptureVerdict
    label_usable: bool
    label_declared: bool
    dispatch_concurrency: VariableReport
    image_ref: str
    exporter_version: str | None

    @property
    def exit_code(self) -> int:
        """0 unless something is genuinely broken.

        A missing session-store configuration is deliberately not broken: OFF is
        the documented default, and an open store is a legitimate deployment.
        """
        return 0


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def _holders(name: str, sources: EnvSources) -> list[tuple[Source, str]]:
    """Every (source, value) pair holding ``name``, in real precedence order."""
    found: list[tuple[Source, str]] = []
    if name in sources.environ:
        found.append((Source.SHELL, sources.environ[name]))
    if sources.vault is not None and name in sources.vault:
        found.append((Source.ONEPASSWORD, sources.vault[name]))
    if name in sources.dotenv:
        found.append((Source.DOTENV, sources.dotenv[name]))
    if name in sources.infra_dotenv:
        found.append((Source.INFRA_DOTENV, sources.infra_dotenv[name]))
    return found


def _attribute_environ(name: str, environ_value: str, sources: EnvSources) -> Source:
    """Decide which source put ``environ_value`` into the process environment.

    ``just`` loads the root ``.env`` before a recipe runs (``set dotenv-load``),
    so a file value is indistinguishable from a shell export by presence alone.
    Matching on the value is the only signal available, and it is the right one:
    if the file and the environment agree, the file explains the value.
    """
    if sources.dotenv.get(name) == environ_value:
        return Source.DOTENV
    if sources.infra_dotenv.get(name) == environ_value:
        return Source.INFRA_DOTENV
    if sources.vault is not None and sources.vault.get(name) == environ_value:
        return Source.ONEPASSWORD
    return Source.SHELL


def resolve_variable(
    name: str,
    sources: EnvSources,
    *,
    default: str | None = None,
) -> VariableReport:
    """Resolve one variable to its effective value and winning source.

    Secrecy is decided by ``_SECRET_NAMES``, not by the caller, so a new call
    site cannot accidentally opt a credential out of redaction.
    """
    is_secret = name in _SECRET_NAMES
    holders = _holders(name, sources)
    present = [(source, value) for source, value in holders if value != ""]

    if not present:
        # A name present but EMPTY everywhere is the same as unset: the
        # session-store validators turn "" into None on purpose.
        losers = tuple(source for source, _ in holders)
        if default is not None:
            return VariableReport(name, Source.DEFAULT, default, is_secret, losers)
        return VariableReport(name, Source.UNSET, None, is_secret, losers)

    winner_source, winner_value = present[0]
    if winner_source is Source.SHELL:
        winner_source = _attribute_environ(name, winner_value, sources)
    elif winner_source is Source.INFRA_DOTENV:
        # infra/.env is not an env_file of any Settings class; it only reaches a
        # process that was launched through a justfile recipe.
        pass

    # A value that reached os.environ FROM a file is one holder, not two: the
    # environ entry and the file entry are the same fact. Excluding both the raw
    # holder and the source it was attributed to keeps ".env (also set in: .env)"
    # off the report.
    raw_winner = present[0][0]
    shadowed = tuple(
        source for source, _ in holders if source is not raw_winner and source is not winner_source
    )
    return VariableReport(name, winner_source, winner_value, is_secret, shadowed)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _load_vault(app_env: str) -> Mapping[str, str] | None:
    """Read the vault item, or return None when 1Password is not consulted.

    Never required. ``op`` missing, unauthenticated, unreachable or slow all
    land on None, and the report says so instead of failing.
    """
    if app_env not in _ENV_TO_VAULT:
        return None
    if not op_available():
        return None
    item = fetch_op_item(_ENV_TO_VAULT[app_env], _OP_ITEM_TITLE)
    if item is None:
        return None
    fields: object = item.get("fields", [])
    if not isinstance(fields, list):
        return None
    values: dict[str, str] = {}
    for field in fields:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(field, dict):
            continue
        label: object = field.get("label", "")  # pyright: ignore[reportUnknownMemberType]
        value: object = field.get("value", "")  # pyright: ignore[reportUnknownMemberType]
        if isinstance(label, str) and isinstance(value, str) and label.strip():
            values[label.strip()] = value
    return values


def collect_sources(repo_root: Path, *, consult_vault: bool = True) -> EnvSources:
    """Gather every candidate source. Only this function touches the outside world."""
    environ = dict(os.environ)
    dotenv = parse_env_file(repo_root / ".env")
    infra_dotenv = parse_env_file(repo_root / "infra" / ".env")

    app_env = (environ.get(ENV_APP_ENVIRONMENT) or dotenv.get(ENV_APP_ENVIRONMENT) or "").strip()
    vault = _load_vault(app_env.lower()) if consult_vault else None
    return EnvSources(environ=environ, dotenv=dotenv, infra_dotenv=infra_dotenv, vault=vault)


def classify_capture(settings: SessionStoreSettings) -> CaptureVerdict:
    """OFF / WARN / OK, using the settings' own properties rather than new rules."""
    if not settings.is_enabled:
        return CaptureVerdict.OFF
    if settings.is_unauthenticated:
        return CaptureVerdict.WARN
    return CaptureVerdict.OK


def _exporter_version() -> str | None:
    """Best-effort read of the exporter version recorded beside the omni pin.

    Deliberately a source read, not a ``docker`` call: the doctor must work with
    no daemon, no network and no registry credentials.
    """
    from syn_shared.settings import workspace_images

    try:
        source = inspect.getsource(workspace_images)
    except OSError:
        return None
    match = _EXPORTER_VERSION.search(source)
    return match.group(1) if match else None


def build_report(sources: EnvSources) -> DoctorReport:
    """Turn raw sources into the structured report. Pure - no I/O."""
    app_environment = resolve_variable(ENV_APP_ENVIRONMENT, sources, default="development")
    tier = (app_environment.value or "development").strip().lower()
    vault = _ENV_TO_VAULT.get(tier)

    store_url = resolve_variable(ENV_SYN_SESSION_STORE_URL, sources)
    store_token = resolve_variable(ENV_SYN_SESSION_STORE_AUTH_TOKEN, sources)
    store_label = resolve_variable(ENV_SYN_SESSION_STORE_LABEL, sources)

    # Reuse the real settings object so OFF/WARN/OK and the label rule can never
    # drift from what the running system does.
    settings = SessionStoreSettings(
        url=store_url.value,
        auth_token=store_token.value,
        label=store_label.value or "",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    if store_label.is_set and not settings.display_label:
        # An unusable label is probably not what the operator believed they set,
        # and echoing it is how a mis-pasted secret reaches a log. Same reasoning
        # as SessionStoreSettings.display_label.
        store_label = replace(
            store_label,
            withhold=True,
            withheld_note="(set, not a usable identifier - value withheld)",
        )

    provider = WorkspaceImageProvider.OMNI_AGENT
    image_ref = f"{workspace_image_name(provider)}@{PINNED_DIGESTS[provider]}"

    return DoctorReport(
        app_environment=app_environment,
        vault=vault,
        vault_consulted=sources.vault_consulted,
        deployment=f"{_DEPLOYMENT_SOURCE}{_DEPLOYMENT_SEPARATOR}{tier}",
        store_url=store_url,
        store_token=store_token,
        store_label=store_label,
        capture=classify_capture(settings),
        label_usable=bool(settings.display_label),
        label_declared=bool(store_label.value and store_label.value.strip()),
        dispatch_concurrency=resolve_variable(
            ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES, sources, default="1"
        ),
        image_ref=image_ref,
        exporter_version=_exporter_version(),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_MARK: Mapping[Severity, str] = {
    Severity.OK: "ok  ",
    Severity.INFO: "    ",
    Severity.WARN: "WARN",
    Severity.ERROR: "FAIL",
}


#: Width the left-hand name column is padded to, so every line in the report
#: has its value and its provenance in the same place.
_NAME_WIDTH = 28


def _variable_line(report: VariableReport, *, show_values: bool) -> str:
    name = report.name.ljust(_NAME_WIDTH)
    line = f"    {name} = {report.display_value(show_values=show_values)}"
    line += f"  [from: {report.source.value}]"
    if report.shadowed:
        also = ", ".join(source.value for source in report.shadowed)
        line += f"  (also set in: {also} - not used)"
    return line


def _plain_line(label: str, value: str) -> str:
    return f"    {label.ljust(_NAME_WIDTH)} = {value}"


#: Report width. Findings carry real explanation, and an unwrapped paragraph in
#: a terminal is a paragraph nobody reads.
_WIDTH = 96


def _wrap_finding(finding: Finding) -> list[str]:
    prefix = f"  {_MARK[finding.severity]} "
    return textwrap.wrap(
        finding.text,
        width=_WIDTH,
        initial_indent=prefix,
        subsequent_indent=" " * len(prefix),
    )


def _capture_findings(report: DoctorReport) -> list[Finding]:
    findings: list[Finding] = []
    if report.capture is CaptureVerdict.OFF:
        findings.append(
            Finding(
                Severity.INFO,
                "Session capture OFF - no SYN_SESSION_STORE_URL is set. This is the "
                "default and it is fine: nothing is injected into workspace "
                "containers and behaviour is identical to having no store at all.",
            )
        )
    elif report.capture is CaptureVerdict.WARN:
        findings.append(
            Finding(
                Severity.WARN,
                "Session capture URL is set but no auth token is. That works only "
                "against an OPEN store. Against an authenticated one the preflight "
                "still passes (it probes an unauthenticated health endpoint), the "
                "workspace runs to completion, and the write is rejected with 401 "
                "at finalize - with the exporter diagnostic suppressed so the "
                "credential cannot leak. You would see a bare failure count and no "
                "cause. Set SYN_SESSION_STORE_AUTH_TOKEN, or ignore this if your "
                "store really is open.",
            )
        )
    else:
        findings.append(Finding(Severity.OK, "Session capture configured (URL + auth token)."))

    if report.label_declared and not report.label_usable:
        findings.append(
            Finding(
                Severity.WARN,
                "SYN_SESSION_STORE_LABEL is set to something that is not a plain "
                "identifier (ASCII letters, digits, dot, underscore, hyphen; 1 to "
                "64 chars), so it is IGNORED and the posture line falls back to "
                "naming the deployment alone. The value is not echoed here on "
                "purpose - it may not be what you think you set.",
            )
        )
    return findings


def render(report: DoctorReport, *, show_values: bool) -> str:
    """Render the whole report as plain text."""
    lines: list[str] = ["Syntropic137 configuration doctor", ""]

    lines.append("Environment")
    lines.append(_variable_line(report.app_environment, show_values=True))
    lines.append(
        _plain_line(
            "1Password vault",
            report.vault
            if report.vault
            else "(none - this environment skips 1Password resolution)",
        )
    )
    lines.append(_plain_line("deployment identity", report.deployment))
    if report.vault_consulted:
        lines.append(_plain_line("vault item", f"{_OP_ITEM_TITLE} (read)"))
    else:
        lines.append(_plain_line("vault item", "1Password not consulted"))
        lines.append(
            "         op is missing, not authenticated, unreachable, or this "
            "environment has no vault."
        )
        lines.append("         Every other line below is still accurate for non-vault sources.")
    lines.append("")

    lines.append(f"Session capture: {report.capture.value}")
    lines.append(_variable_line(report.store_url, show_values=show_values))
    lines.append(_variable_line(report.store_token, show_values=show_values))
    lines.append(_variable_line(report.store_label, show_values=show_values))
    for finding in _capture_findings(report):
        lines.extend(_wrap_finding(finding))
    lines.append("")

    lines.append("Trigger dispatch")
    lines.append(_variable_line(report.dispatch_concurrency, show_values=True))
    lines.append("")

    lines.append("Workspace image (pinned)")
    lines.append(_plain_line("omni-agent", report.image_ref))
    lines.append(
        _plain_line(
            "session exporter",
            f"apss-session-exporter {report.exporter_version}"
            if report.exporter_version
            else "(version not recorded beside the pin)",
        )
    )
    lines.append("")

    if not show_values:
        lines.append("Secret values are redacted. Re-run with --show-values to print them.")
    return "\n".join(lines)


def _severities(report: DoctorReport) -> Iterable[Severity]:
    return (finding.severity for finding in _capture_findings(report))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="just doctor",
        description="Report Syntropic137 configuration health and where each value came from.",
    )
    parser.add_argument(
        "--show-values",
        action="store_true",
        help="Print real values instead of redacting secrets. Off by default.",
    )
    parser.add_argument(
        "--no-1password",
        action="store_true",
        help="Skip the 1Password lookup entirely (faster, fully offline).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to read .env and infra/.env from. Default: cwd.",
    )
    args = parser.parse_args(argv)

    sources = collect_sources(args.repo_root, consult_vault=not args.no_1password)
    report = build_report(sources)
    print(render(report, show_values=args.show_values))
    if any(severity is Severity.ERROR for severity in _severities(report)):
        return 1
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
