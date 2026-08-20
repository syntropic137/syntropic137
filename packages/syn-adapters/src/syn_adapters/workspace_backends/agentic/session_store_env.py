"""Build the session-store contract injected into workspace containers.

The session-store capability ships inside the agentic-primitives workspace
image and activates purely from environment variables. Syntropic137's entire
job is to write those variables into the container environment at provision
time; there is no capture code on this side.

Opt-in, default OFF
-------------------
If no store URL is configured, :func:`build_session_store_env` returns an EMPTY
dict — not ``PROVIDER=none``, not empty values, nothing. With
``AGENTIC_SESSION_STORE_PROVIDER`` unset the capability is a complete no-op in
the container (no init, no doctor, no finalize), so a self-hoster with no
SeshMagic instance sees byte-identical behaviour to having no integration at
all. That guarantee is the point of this module and is covered by tests.

Reserved keys
-------------
The ``AGENTIC_SESSION_STORE_*`` variables are RESERVED by this adapter (seven
names, of which DEPLOYMENT is emitted only when known). The
public workspace API accepts arbitrary ``extra_environment`` from callers, so
without an explicit rule a caller could set ``AGENTIC_SESSION_STORE_PROVIDER``
itself and switch on in-image capture while the host-side setting is OFF, or
redirect an enabled capture at a store of its own choosing.
:func:`apply_session_store_env` therefore strips every reserved key from
caller-supplied environment first, then layers this module's own values on top
(when enabled). A stripped key is logged by NAME only — never by value, because
one of them is the write token.

Partition safety
----------------
The capability HARD-FAILS the workspace if the partition is absolute or
contains ``..``. Identifiers reaching this module come from the orchestration
domain and are normally opaque ids, but they are sanitised here rather than
trusted: a workflow-supplied id must never be able to take down provisioning or
escape its partition prefix.

Tag identity
------------
Tags are the join key: a store row is matched back to a Syn137 execution by
them, so a tag value must still EQUAL the identifier it names. Values are
therefore percent-encoded rather than having their delimiters substituted — see
:func:`encode_tag_value`.

See ADR-021 (Isolated Workspace Architecture) for the surrounding container
lifecycle.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

from syn_shared.env_constants import (
    ENV_AGENTIC_SESSION_STORE_AUTH,
    ENV_AGENTIC_SESSION_STORE_DEPLOYMENT,
    ENV_AGENTIC_SESSION_STORE_PARTITION,
    ENV_AGENTIC_SESSION_STORE_PROVIDER,
    ENV_AGENTIC_SESSION_STORE_SPOOL,
    ENV_AGENTIC_SESSION_STORE_TAGS,
    ENV_AGENTIC_SESSION_STORE_URL,
    SESSION_STORE_CONTRACT_ENV_VARS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_shared.settings.session_store import SessionStoreSettings

logger = logging.getLogger(__name__)

__all__ = [
    "TAG_DEPLOYMENT",
    "TAG_EXECUTION_ID",
    "TAG_PHASE_ID",
    "TAG_SOURCE",
    "TAG_WORKFLOW_ID",
    "TAG_WORKSPACE_ID",
    "apply_session_store_env",
    "build_partition",
    "build_session_store_env",
    "decode_tag_value",
    "encode_tag_value",
    "sanitize_partition_segment",
]

# Tag keys are part of the join contract with the session store: a row in the
# store is matched back to a Syn137 execution by these keys. Declared once here
# so the store-side query and this producer cannot drift apart silently.
TAG_SOURCE = "source"
TAG_EXECUTION_ID = "execution_id"
TAG_WORKSPACE_ID = "workspace_id"
TAG_WORKFLOW_ID = "workflow_id"
TAG_PHASE_ID = "phase_id"
TAG_DEPLOYMENT = "deployment"

#: Value of the ``source`` tag. Lets the store distinguish Syn137-originated
#: sessions from sessions captured by any other agentic-primitives consumer.
SOURCE_SYNTROPIC137 = "syntropic137"

#: Separator in the ``<app>__<tier>`` deployment convention (APS-V1-0004
#: ``origin.deployment``). Double underscore because app names and hostnames
#: routinely contain hyphens and dots but not ``__``, so a consumer can split
#: on the FIRST occurrence without ambiguity.
DEPLOYMENT_SEPARATOR = "__"


def deployment_identity(app_environment: str) -> str:
    """``syntropic137__<app_environment>`` - which deployment produced a session.

    This is deliberately NOT the same question as the envelope's
    ``origin.environment``, which is the CLASS of runtime (``container``,
    ``workflow``, ``local``, ``vps``) and is set by the capability. Every
    Syn137 workspace reports the same class, so without a deployment identity a
    multi-tier install is unattributable: dev, beta and prod are indistinguishable
    in the corpus.

    The tier is the raw ``AppEnvironment`` value (``development``, ``beta``,
    ``production``, ``selfhost``), not an abbreviation. A mapping table like
    ``development -> dev`` is a second source of truth that drifts from the enum
    the rest of the platform switches on, and buys nothing but four characters.
    """
    return f"{SOURCE_SYNTROPIC137}{DEPLOYMENT_SEPARATOR}{app_environment}"


#: Substituted for any character that is not safe in a single path segment.
_UNSAFE_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9._-]")

#: Collapses ``..`` (and longer runs) so a segment can never traverse upward.
_DOT_RUN = re.compile(r"\.{2,}")

#: Placeholder for an identifier that sanitises down to nothing.
_EMPTY_SEGMENT = "unknown"

#: Percent-encoding leaves these characters untouched. Everything else — the
#: ``,`` and ``:`` framing delimiters, whitespace, ``%`` itself, non-ASCII — is
#: escaped, so encoding is injective and ``decode_tag_value`` recovers the
#: original identifier exactly.
_TAG_VALUE_SAFE = ""


def sanitize_partition_segment(raw: str | None) -> str:
    """Make ``raw`` safe as one segment of a relative partition path.

    Guarantees the result is non-empty, contains no path separator, is not
    absolute, and cannot contain ``..``. The capability rejects the workspace
    outright on any of those, so this is a hard requirement rather than
    cosmetics.
    """
    if not raw:
        return _EMPTY_SEGMENT

    # Any separator (or other unsafe char) becomes "_", so "/etc" -> "_etc"
    # and the result can never be absolute.
    cleaned = _UNSAFE_SEGMENT_CHARS.sub("_", raw)
    # ".." -> "." so no segment can traverse upward.
    cleaned = _DOT_RUN.sub(".", cleaned)
    # A leading/trailing "." is either a hidden-file marker or the residue of a
    # collapsed traversal; neither is wanted in a partition segment.
    cleaned = cleaned.strip(".")

    return cleaned or _EMPTY_SEGMENT


def encode_tag_value(raw: str) -> str:
    """Percent-encode ``raw`` so it is safe inside the ``key:value`` framing.

    Substituting the delimiters (the previous behaviour) collapsed ``phase:a``,
    ``phase,a`` and ``phase_a`` onto one tag and stored a value that no longer
    equalled the real identifier — which breaks the whole point of these tags,
    namely joining a store row back to the Syn137 execution that produced it.

    Percent-encoding (RFC 3986) is injective and reversible, so the join
    survives. For every identifier that actually occurs in practice (kebab- or
    snake-cased slugs, uuid4s, ``exec-<hex>``) encoding is the identity
    function, so this changes no real tag value; it only stops the pathological
    ones from lying. Rejection was considered and dropped: ``workflow_id`` and
    ``phase_id`` come from author-written workflow YAML whose schema constrains
    only length, never the character set, so a delimiter is *legal* input and
    failing provisioning over one would be an outage, not a safety measure.

    The store side recovers the identifier with :func:`decode_tag_value` (or any
    standard percent-decoder).
    """
    return quote(raw.strip(), safe=_TAG_VALUE_SAFE)


def decode_tag_value(encoded: str) -> str:
    """Inverse of :func:`encode_tag_value`. Declared here so the round trip is
    testable and the store-side decoder has one authoritative reference."""
    return unquote(encoded)


def build_partition(execution_id: str, workspace_id: str) -> str:
    """Relative ``<execution_id>/<workspace_id>`` partition path.

    Public because the capture verdict records it too: a backfill pass needs
    the identity the transcripts were spooled under, and deriving it a second
    time somewhere else is how two spellings of the same thing drift apart.
    """
    return "/".join(
        (
            sanitize_partition_segment(execution_id),
            sanitize_partition_segment(workspace_id),
        )
    )


def _build_tags(
    *,
    execution_id: str,
    workspace_id: str,
    workflow_id: str | None,
    phase_id: str | None,
    deployment: str | None,
) -> str:
    """Comma-separated ``key:value`` tags that join a store row to an execution.

    Optional context (workflow, phase) is emitted only when actually present on
    the isolation config, so a tag is never a lie about missing data.
    """
    pairs: list[tuple[str, str | None]] = [
        (TAG_SOURCE, SOURCE_SYNTROPIC137),
        (TAG_EXECUTION_ID, execution_id),
        (TAG_WORKSPACE_ID, workspace_id),
        (TAG_WORKFLOW_ID, workflow_id),
        (TAG_PHASE_ID, phase_id),
        (TAG_DEPLOYMENT, deployment),
    ]

    rendered: list[str] = []
    for key, value in pairs:
        if not value:
            continue
        safe = encode_tag_value(value)
        if safe:
            rendered.append(f"{key}:{safe}")
    return ",".join(rendered)


def build_session_store_env(
    settings: SessionStoreSettings,
    *,
    execution_id: str,
    workspace_id: str,
    workflow_id: str | None = None,
    phase_id: str | None = None,
    deployment: str | None = None,
) -> dict[str, str]:
    """Return the session-store variables for one workspace container.

    Returns an EMPTY dict when no store is configured. Callers must merge the
    result rather than branching, so the disabled path adds literally nothing to
    the container environment.

    The auth token is read from the settings object at this single point and
    written straight into the returned mapping. It is never logged, never put in
    an exception message, and never placed in a container label (labels are
    readable by anyone who can run ``docker inspect``).
    """
    if not settings.is_enabled:
        return {}

    # `is_enabled` already proved url is a non-empty string.
    url = settings.url or ""

    env = {
        ENV_AGENTIC_SESSION_STORE_PROVIDER: settings.provider,
        ENV_AGENTIC_SESSION_STORE_URL: url.strip(),
        ENV_AGENTIC_SESSION_STORE_SPOOL: settings.spool_dir,
        ENV_AGENTIC_SESSION_STORE_PARTITION: build_partition(execution_id, workspace_id),
        ENV_AGENTIC_SESSION_STORE_TAGS: _build_tags(
            execution_id=execution_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            deployment=deployment,
        ),
    }

    # Its OWN variable, not just a tag. The exporter stamps origin.deployment
    # from SESSION_STORE_ORIGIN_DEPLOYMENT, which the capability adapter maps
    # from this one; it does not read tags for origin. Sending the deployment
    # only as a tag - which is what this did - means every captured session
    # arrives with origin.deployment null while syn137's own indicator records
    # the deployment it MEANT to send and looks entirely healthy.
    #
    # It stays in the tags as well: tags are what the store filters on, and
    # dropping it there would trade one gap for another.
    if deployment:
        env[ENV_AGENTIC_SESSION_STORE_DEPLOYMENT] = deployment

    # AUTH is always emitted when the store is on, even if the operator runs an
    # unauthenticated store: the capability treats an empty token as "no auth
    # header" rather than as a misconfiguration.
    env[ENV_AGENTIC_SESSION_STORE_AUTH] = settings.auth_value

    return env


def apply_session_store_env(
    caller_environment: Mapping[str, str],
    settings: SessionStoreSettings,
    *,
    execution_id: str,
    workspace_id: str,
    workflow_id: str | None = None,
    phase_id: str | None = None,
    deployment: str | None = None,
) -> dict[str, str]:
    """Return ``caller_environment`` with the reserved contract keys enforced.

    This is the ONLY function the adapter should use. It is deliberately not a
    plain ``environment.update(build_session_store_env(...))`` because that
    leaves caller-supplied reserved keys in place on the disabled path, which
    would let any caller of the public workspace API turn on in-image capture by
    passing ``extra_environment`` — defeating the opt-in switch entirely.

    Behaviour:

    * **Disabled** — every reserved key is removed and nothing is added, so the
      container environment is byte-identical to having no integration.
    * **Enabled** — every reserved key is removed and then re-supplied from this
      execution's own contract, so the adapter's values always win.

    Stripping is chosen over raising: these keys belong to the workspace image's
    capability namespace, not to Syn137 callers, so there is no legitimate reason
    for one to be supplied, and failing provisioning on an illegitimate input
    would turn a hardening measure into an outage (and, on the disabled path,
    into a way to make a workspace unprovisionable). The removal is surfaced at
    WARNING so an operator can discover it in logs.
    """
    environment = dict(caller_environment)

    reserved_from_caller = sorted(SESSION_STORE_CONTRACT_ENV_VARS & environment.keys())
    if reserved_from_caller:
        for key in reserved_from_caller:
            del environment[key]
        # Names only. One of these keys carries the write token, so no value from
        # this set may ever reach a log record.
        logger.warning(
            "Ignoring caller-supplied session-store variable(s) %s: these names are "
            "reserved by the workspace adapter and are set from the host-side "
            "SYN_SESSION_STORE_* settings only (execution=%s, workspace=%s). "
            "Values are not logged.",
            ", ".join(reserved_from_caller),
            execution_id,
            workspace_id,
        )

    # A store URL with no write token is a legitimate deployment (an open store
    # on a trusted network), so this warns rather than refusing. But it is also
    # the shape of the most common misconfiguration, and its failure mode is
    # silent: the capability's preflight probes an UNAUTHENTICATED health
    # endpoint, so every check passes and the workspace starts normally, while
    # the write is rejected 401 at finalize with the exporter's diagnostic
    # deliberately suppressed to avoid leaking the credential. The operator is
    # left with a bare failure count and no cause. Say it once, here, loudly.
    if settings.is_unauthenticated:
        logger.warning(
            "Session store is configured WITHOUT a write token "
            "(SYN_SESSION_STORE_AUTH_TOKEN is unset). If the store requires "
            "authentication, every session from this workspace will be rejected "
            "at upload and the failure will not name a cause "
            "(execution=%s, workspace=%s).",
            execution_id,
            workspace_id,
        )

    environment.update(
        build_session_store_env(
            settings,
            execution_id=execution_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            deployment=deployment,
        )
    )
    return environment
