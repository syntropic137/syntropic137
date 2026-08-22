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
``InfraSettings``); it reaches only the recipes that go through
``scripts/resolve_infra_env.py``. It can therefore never supply the effective
value of a name this report resolves, so it is never a winner and never a
shadowed loser: it is listed separately as INERT, a copy nothing on this path
reads. Reporting it as the winner would let an infra-only
``SYN_SESSION_STORE_URL`` show capture as ON while it is off.

Two caveats this report is explicit about rather than papering over:

*Attribution under ``just`` is inferred, not proven.* The justfile sets
``dotenv-load``, so the root ``.env`` has ALREADY been merged into the process
environment by the time a recipe runs. A name is attributed to ``.env`` when the
environment value equals the file value, and to ``shell`` only when the
environment holds a value no file explains - but a shell export of a byte-identical
value is indistinguishable from the file having supplied it. Such a line is marked
``inferred`` so the report never claims more than it knows. The vault is NOT a
candidate explanation here: this process never calls ``resolve_op_secrets``, so
nothing in ``os.environ`` can have come from 1Password, however the values compare.

*An explicitly empty environment variable is a real value, not an absence.*
``inject_fields`` treats ``""`` as absent and writes the vault field over it, but
if the vault holds nothing then pydantic reads that ``""`` from ``os.environ``
before it ever opens its ``env_file``. ``SYN_SESSION_STORE_URL=`` in the shell
therefore beats a populated ``.env`` line and capture is OFF. The report says so.

Redaction
---------
Secret values are never printed. ``SYN_SESSION_STORE_URL`` counts as secret:
its own field docstring notes that every part of a URL is operator-supplied and
could carry a credential, which is why the startup posture line logs no part of
it. ``--show-values`` opts out, deliberately, per invocation.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from syn_shared.env_constants import (
    ENV_APP_ENVIRONMENT,
    ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES,
)
from syn_shared.settings.config import AppEnvironment
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
    PINNED_EXPORTER_VERSIONS,
    WorkspaceImageProvider,
    workspace_image_name,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CaptureVerdict",
    "DoctorReport",
    "Severity",
    "Source",
    "VariableReport",
    "build_report",
    "classify_capture",
    "collect_sources",
    "main",
    "render",
    "resolve_variable",
    "resolver_tier",
]


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
    #: The settings object could not be built at all, so no posture can be
    #: derived. Distinct from OFF: OFF is a working system with capture
    #: disabled, INVALID is a system that will not start.
    INVALID = "INVALID"


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
    #: Sources that also hold this name, are genuinely read on this path, and
    #: lost. Reported so a shadowed value is visible rather than mysterious.
    shadowed: tuple[Source, ...]
    #: Sources that hold this name but are not read at all on this path, so they
    #: never competed. ``infra/.env`` is the only one today. Kept apart from
    #: ``shadowed`` because "lost a race" and "was never in the race" are
    #: different facts, and conflating them is how an operator edits the file
    #: that was never going to matter.
    inert: tuple[Source, ...] = ()
    #: True when ``.env`` could equally be a byte-identical shell export. See
    #: the module docstring: presence alone cannot separate them under ``just``.
    inferred: bool = False
    #: True when the process environment holds this name as an empty string and
    #: no vault value replaced it. The empty value is what pydantic reads, so it
    #: beats any file - the variable is off, not merely unconfigured.
    empty_override: bool = False
    #: Set for a non-secret value that still must not be echoed - see
    #: ``withheld_note``. Independent of ``is_secret`` so the reason survives.
    withhold: bool = False
    withheld_note: str = "(set, value withheld)"

    @property
    def is_set(self) -> bool:
        return self.value is not None and self.value != ""

    def display_value(self, *, show_values: bool) -> str:
        if self.empty_override:
            return "(set to empty - overrides every file)"
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
    #: Variables SessionStoreSettings refused. Names only, never values: the
    #: whole point of the URL being secret is that a malformed one is still
    #: secret, and a rejected value is the likeliest to be a mis-paste.
    rejected_names: tuple[str, ...]
    label_usable: bool
    label_declared: bool
    dispatch_concurrency: VariableReport
    image_ref: str
    exporter_version: str | None

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Every finding, in report order. The single source for the exit code."""
        return (*_environment_findings(self), *_capture_findings(self))

    @property
    def exit_code(self) -> int:
        """0 unless something is genuinely broken.

        A missing session-store configuration is deliberately NOT broken: OFF is
        the documented default and an open store is a legitimate deployment, so
        WARN must never fail the command. Only a value the application itself
        would reject at startup earns a non-zero exit - otherwise operators
        learn to ignore the exit code, and then it protects nothing.
        """
        return 1 if any(f.severity is Severity.ERROR for f in self.findings) else 0


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def _holders(name: str, sources: EnvSources) -> list[tuple[Source, str]]:
    """Every (source, value) pair that can actually SUPPLY ``name``, in precedence order.

    ``infra/.env`` is deliberately absent: no ``Settings`` class lists it as an
    ``env_file`` and ``just doctor`` does not export it, so it can never be the
    effective value. It is surfaced separately by ``_inert_sources``.
    """
    found: list[tuple[Source, str]] = []
    if name in sources.environ:
        found.append((Source.SHELL, sources.environ[name]))
    if sources.vault is not None and name in sources.vault:
        found.append((Source.ONEPASSWORD, sources.vault[name]))
    if name in sources.dotenv:
        found.append((Source.DOTENV, sources.dotenv[name]))
    return found


def _inert_sources(name: str, sources: EnvSources) -> tuple[Source, ...]:
    """Files that DECLARE ``name`` but that nothing on this path reads.

    Membership, not truthiness: ``SYN_SESSION_STORE_URL=`` in infra/.env is a
    declaration an operator can see in the file and reasonably expect to matter.
    Hiding it because it happens to be blank is the same silence this command
    exists to break.
    """
    if name in sources.infra_dotenv:
        return (Source.INFRA_DOTENV,)
    return ()


def _attribute_environ(name: str, environ_value: str, sources: EnvSources) -> tuple[Source, bool]:
    """Decide which source put ``environ_value`` into the process environment.

    Returns the source and whether the answer is INFERRED rather than proven.

    ``just`` loads the root ``.env`` before a recipe runs (``set dotenv-load``),
    so a file value is indistinguishable from a shell export of the same bytes.
    Matching on the value is the only signal available, and it is a real one -
    but it is evidence of compatibility, not of origin, so the caller marks the
    line accordingly instead of asserting a source it cannot know.

    1Password is NOT a candidate. This process never calls
    ``resolve_op_secrets``, so no vault field was injected into ``os.environ``
    here no matter how the values compare; claiming otherwise would name a
    source that did nothing and would hide the real one.
    """
    if sources.dotenv.get(name) == environ_value:
        return Source.DOTENV, True
    return Source.SHELL, False


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
    inert = _inert_sources(name, sources)
    environ_value = sources.environ.get(name)
    vault_value = sources.vault.get(name) if sources.vault is not None else None

    present = [(holder, value) for holder, value in holders if value != ""]

    if environ_value == "" and not vault_value and present:
        # Explicitly empty in the process environment, nothing in the vault to
        # displace it, and something else does hold a value. `inject_fields`
        # skips the name, pydantic reads os.environ before it opens its
        # env_file, and the empty string is what the settings see. The populated
        # `.env` line does NOT win, and reporting that it did would show capture
        # ON for an operator who had just turned it off.
        #
        # Empty with nothing to override is not an override at all - it falls
        # through to the ordinary unset path below.
        source, inferred = _attribute_environ(name, "", sources)
        losers = tuple(holder for holder, _ in present if holder is not source)
        return VariableReport(
            name,
            source,
            None,
            is_secret,
            losers,
            inert=inert,
            inferred=inferred,
            empty_override=True,
        )

    if not present:
        # A name present but EMPTY everywhere is the same as unset: the
        # session-store validators turn "" into None on purpose.
        losers = tuple(holder for holder, _ in holders)
        if default is not None:
            return VariableReport(name, Source.DEFAULT, default, is_secret, losers, inert=inert)
        return VariableReport(name, Source.UNSET, None, is_secret, losers, inert=inert)

    raw_winner, winner_value = present[0]
    winner_source = raw_winner
    inferred = False
    if raw_winner is Source.SHELL:
        winner_source, inferred = _attribute_environ(name, winner_value, sources)

    # A value that reached os.environ FROM a file is one holder, not two: the
    # environ entry and the file entry are the same fact. Excluding both the raw
    # holder and the source it was attributed to keeps ".env (also set in: .env)"
    # off the report.
    shadowed = tuple(
        holder for holder, _ in holders if holder is not raw_winner and holder is not winner_source
    )
    return VariableReport(
        name,
        winner_source,
        winner_value,
        is_secret,
        shadowed,
        inert=inert,
        inferred=inferred,
    )


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _vault_fields(item: Mapping[str, object]) -> Mapping[str, str]:
    """Flatten a 1Password item into label -> value exactly as the runtime sees it.

    `inject_fields` skips empty values and never overwrites a label it has
    already injected, so on a duplicated label the FIRST non-empty field is what
    the running process gets. Last-write-wins here would make the doctor name a
    value nothing ever received - the exact failure it exists to prevent.
    """
    fields = item.get("fields", [])
    if not isinstance(fields, list):
        return {}
    values: dict[str, str] = {}
    for field in fields:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(field, dict):
            continue
        label: object = field.get("label", "")  # pyright: ignore[reportUnknownMemberType]
        value: object = field.get("value", "")  # pyright: ignore[reportUnknownMemberType]
        if isinstance(label, str) and isinstance(value, str) and label.strip() and value:
            values.setdefault(label.strip(), value)
    return values


def _load_vault(app_env: str) -> Mapping[str, str] | None:
    """Read the vault item, or return None when 1Password is not consulted.

    Never required. An unmapped environment, `op` missing, unauthenticated,
    unreachable or slow all land on None, and the report says so instead of
    failing. A diagnostic that dies when a dependency is absent is useless
    exactly when it is needed.
    """
    if app_env not in _ENV_TO_VAULT or not op_available():
        return None
    item = fetch_op_item(_ENV_TO_VAULT[app_env], _OP_ITEM_TITLE)
    if item is None:
        return None
    return _vault_fields(item)


def resolver_tier(sources: EnvSources) -> str:
    """The APP_ENVIRONMENT that `resolve_op_secrets` would act on, or "".

    Empty means the resolver returns before it looks a vault up, so no vault is
    read. Deliberately NOT the pydantic default: `AppEnvironment` falls back to
    development, but the 1Password resolver never does.

    Both the vault fetch and the reported vault name go through this one
    function so they cannot disagree - that split is exactly how the report came
    to claim `syn137-dev` while saying 1Password was not consulted.
    """
    app_environment = resolve_variable(ENV_APP_ENVIRONMENT, sources, default="development")
    if app_environment.source is Source.DEFAULT or app_environment.empty_override:
        return ""
    return (app_environment.value or "").strip().lower()


def collect_sources(repo_root: Path, *, consult_vault: bool = True) -> EnvSources:
    """Gather every candidate source. Only this function touches the outside world."""
    environ = dict(os.environ)
    dotenv = parse_env_file(repo_root / ".env")
    infra_dotenv = parse_env_file(repo_root / "infra" / ".env")

    # The vault is one more candidate source, so it has to be fetched before the
    # EnvSources is complete - but which vault depends on APP_ENVIRONMENT, which
    # is resolved from the other three. Resolve it against a vault-less view
    # first: APP_ENVIRONMENT is never a vault field (it selects the vault), so
    # nothing is lost.
    without_vault = EnvSources(
        environ=environ, dotenv=dotenv, infra_dotenv=infra_dotenv, vault=None
    )
    vault = _load_vault(resolver_tier(without_vault)) if consult_vault else None
    return EnvSources(environ=environ, dotenv=dotenv, infra_dotenv=infra_dotenv, vault=vault)


def classify_capture(settings: SessionStoreSettings) -> CaptureVerdict:
    """OFF / WARN / OK, using the settings' own properties rather than new rules."""
    if not settings.is_enabled:
        return CaptureVerdict.OFF
    if settings.is_unauthenticated:
        return CaptureVerdict.WARN
    return CaptureVerdict.OK


def _exporter_version(provider: WorkspaceImageProvider) -> str | None:
    """The exporter version recorded beside the pin, or None if that image has none."""
    return PINNED_EXPORTER_VERSIONS.get(provider)


#: The settings field names, as the operator sees them in their environment.
_FIELD_TO_ENV: Mapping[str, str] = {
    "url": ENV_SYN_SESSION_STORE_URL,
    "auth_token": ENV_SYN_SESSION_STORE_AUTH_TOKEN,
    "label": ENV_SYN_SESSION_STORE_LABEL,
}


def _build_settings(
    store_url: VariableReport,
    store_token: VariableReport,
    store_label: VariableReport,
) -> tuple[SessionStoreSettings | None, tuple[str, ...]]:
    """Build the real settings, or report which variables it refused.

    `SessionStoreSettings` rejects a URL with whitespace inside it, because a
    pasted line break cannot be guessed away. That rejection is correct - and it
    means the doctor is handed a value that raises on construction. Letting it
    propagate would end the command in a traceback on exactly the
    misconfiguration it exists to diagnose, which is the one moment an operator
    most needs it to keep talking.

    Only the NAMES come back. A value pydantic refused is the likeliest of all
    to be a mis-paste of something else, and the URL is secret here by design.
    """
    try:
        settings = SessionStoreSettings(
            url=store_url.value,
            auth_token=store_token.value,
            label=store_label.value or "",
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )
    except ValidationError as error:
        names = {
            _FIELD_TO_ENV.get(str(location[0]), str(location[0]))
            for err in error.errors()
            if (location := err["loc"])
        }
        return None, tuple(sorted(names))
    return settings, ()


def build_report(sources: EnvSources) -> DoctorReport:
    """Turn raw sources into the structured report. Pure - no I/O."""
    app_environment = resolve_variable(ENV_APP_ENVIRONMENT, sources, default="development")
    tier = (app_environment.value or "development").strip().lower()

    # The vault is NOT derived from the defaulted tier. `resolve_op_secrets`
    # returns early on an empty APP_ENVIRONMENT, before it ever looks the vault
    # up, so with the variable unset no vault is read at all - naming syn137-dev
    # would advertise an association the runtime never makes. The DEPLOYMENT
    # identity does use the default, because `AppEnvironment` really does fall
    # back to development and that is what gets stamped on a captured session.
    vault = _ENV_TO_VAULT.get(resolver_tier(sources))

    store_url = resolve_variable(ENV_SYN_SESSION_STORE_URL, sources)
    store_token = resolve_variable(ENV_SYN_SESSION_STORE_AUTH_TOKEN, sources)
    store_label = resolve_variable(ENV_SYN_SESSION_STORE_LABEL, sources)

    # Reuse the real settings object so OFF/WARN/OK and the label rule can never
    # drift from what the running system does.
    settings, rejected_names = _build_settings(store_url, store_token, store_label)

    if settings is not None and store_label.is_set and not settings.display_label:
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
        capture=classify_capture(settings) if settings else CaptureVerdict.INVALID,
        rejected_names=rejected_names,
        label_usable=bool(settings and settings.display_label),
        label_declared=bool(store_label.value and store_label.value.strip()),
        dispatch_concurrency=resolve_variable(
            ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES, sources, default="1"
        ),
        image_ref=image_ref,
        exporter_version=_exporter_version(provider),
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
    origin = report.source.value
    if report.inferred:
        origin += ", inferred"
    line += f"  [from: {origin}]"
    if report.shadowed:
        also = ", ".join(source.value for source in report.shadowed)
        line += f"  (also set in: {also} - not used)"
    if report.inert:
        also = ", ".join(source.value for source in report.inert)
        line += f"  (also set in: {also} - never read on this path)"
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


_KNOWN_TIERS = ", ".join(member.value for member in AppEnvironment)


def _environment_findings(report: DoctorReport) -> list[Finding]:
    """Problems with the tier itself, which decides vault, deployment and network."""
    tier = (report.app_environment.value or "").strip().lower()
    if tier and tier not in {member.value for member in AppEnvironment}:
        return [
            Finding(
                Severity.ERROR,
                f"APP_ENVIRONMENT={tier!r} is not a known environment. Settings would "
                f"reject it at startup, so nothing runs with this value. It also "
                f"silently selects no 1Password vault, which is why an unusable tier "
                f"can look like missing secrets rather than a typo. Known: "
                f"{_KNOWN_TIERS}.",
            )
        ]
    return []


def _capture_findings(report: DoctorReport) -> list[Finding]:
    findings: list[Finding] = []
    if report.capture is CaptureVerdict.INVALID:
        rejected = ", ".join(report.rejected_names)
        return [
            Finding(
                Severity.ERROR,
                f"Session-store settings could not be built: {rejected} was rejected as "
                "malformed. The most common cause is a value pasted with a line break or "
                "a stray space inside it, which is invisible in a vault UI. The API would "
                "fail to start with this configuration. The value is not echoed here - a "
                "value that failed validation is the likeliest of all to be a mis-paste "
                "of something else.",
            )
        ]
    if report.capture is CaptureVerdict.OFF:
        findings.append(
            Finding(
                Severity.INFO,
                "Session capture OFF - SYN_SESSION_STORE_URL holds no value. This is "
                "the default and it is fine: nothing is injected into workspace "
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


_INFERRED_LEGEND = (
    'A source marked "inferred" was matched by value, not observed: `just` sets dotenv-load, so '
    ".env is already in the process environment and a shell export of the same bytes looks "
    "identical. The value is right either way; only which file to edit is uncertain."
)

_INERT_LEGEND = (
    'A source marked "never read on this path" holds the name but cannot supply it: infra/.env '
    "is not the env_file of any Settings class and reaches only the recipes that export it "
    "explicitly. Editing it will not change the value above."
)


def _environment_section(report: DoctorReport) -> list[str]:
    if report.vault:
        vault_line = report.vault
    elif report.app_environment.source is Source.DEFAULT or report.app_environment.empty_override:
        vault_line = "(none - APP_ENVIRONMENT is unset, so vault resolution is skipped entirely)"
    else:
        vault_line = "(none - this environment skips 1Password resolution)"

    lines = [
        "Environment",
        _variable_line(report.app_environment, show_values=True),
        _plain_line("1Password vault", vault_line),
        _plain_line("deployment identity", report.deployment),
    ]
    if report.vault_consulted:
        lines.append(_plain_line("vault item", f"{_OP_ITEM_TITLE} (read)"))
        return lines
    lines.append(_plain_line("vault item", "1Password not consulted"))
    lines.append(
        "         APP_ENVIRONMENT names no vault, or op is missing, not "
        "authenticated, or unreachable."
    )
    lines.append("         Every other line below is still accurate for non-vault sources.")
    return lines


def _legend(report: DoctorReport) -> list[str]:
    """Explain the two annotations that would otherwise read as hedging."""
    variables = (
        report.app_environment,
        report.store_url,
        report.store_token,
        report.store_label,
        report.dispatch_concurrency,
    )
    lines: list[str] = []
    if any(variable.inferred for variable in variables):
        lines.extend(_wrap_finding(Finding(Severity.INFO, _INFERRED_LEGEND)))
    if any(variable.inert for variable in variables):
        lines.extend(_wrap_finding(Finding(Severity.INFO, _INERT_LEGEND)))
    return lines


def render(report: DoctorReport, *, show_values: bool) -> str:
    """Render the whole report as plain text."""
    lines: list[str] = ["Syntropic137 configuration doctor", ""]
    lines.extend(_environment_section(report))
    for finding in _environment_findings(report):
        lines.extend(_wrap_finding(finding))
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

    lines.extend(_legend(report))
    if not show_values:
        lines.append("Secret values are redacted. Re-run with --show-values to print them.")
    return "\n".join(lines)


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
        help=(
            "Repository root whose .env and infra/.env are read. Default: cwd. This "
            "changes which FILES are parsed, never the process environment - `just` "
            "has already loaded the invoking root's .env by the time this runs, so "
            "run from the root you mean to diagnose."
        ),
    )
    args = parser.parse_args(argv)

    sources = collect_sources(args.repo_root, consult_vault=not args.no_1password)
    report = build_report(sources)
    print(render(report, show_values=args.show_values))
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
