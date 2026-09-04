"""Shared, type-safe identifiers for workflow phase agents.

These replace bare string literals ("claude" / "codex") that were
previously compared in many places across the domain, adapter, and API
layers. `StrEnum` members compare equal to their string value, so a loose
``provider: str`` field can still be compared against a member
(``provider == AgentProvider.CODEX``) without changing the field type.
"""

from __future__ import annotations

from enum import StrEnum


class AgentProvider(StrEnum):
    """A workflow phase's ``agent_config.provider`` value.

    The domain ``provider`` field stays a plain ``str`` (it also accepts
    test-only values like ``"mock"``); these members are the KNOWN production
    providers to compare against, never a bare literal.
    """

    CLAUDE = "claude"
    """Default headless ``claude -p`` docker-exec path."""

    CODEX = "codex"
    """Headless ``codex exec`` docker-exec path (the codex bridge)."""


class PhaseSandbox(StrEnum):
    """How much authority a phase's agent process is granted.

    Provider-neutral on purpose: the same declaration must mean the same
    thing whichever harness runs the phase, so a workflow author does not
    have to know that codex spells this ``--sandbox`` and claude spells it
    ``--allowedTools``. Mapping to a specific CLI flag belongs in the
    command builder, not in the workflow definition.

    Ordered least to most authority. Prefer the least a phase can finish
    with: a phase that cannot write cannot invent work it was asked to
    check (#1157, #1161).
    """

    READ_ONLY = "read-only"
    """Read and search only. The correct level for any review, verify or
    audit phase - it makes "the verifier does not modify what it certifies"
    an enforced property rather than a sentence in a prompt."""

    WORKSPACE_WRITE = "workspace-write"
    """Read, write and run commands inside the workspace. No network. The
    default for phases that produce changes."""

    FULL_ACCESS = "full-access"
    """Unrestricted filesystem access AND network egress. Required only by a
    phase that must reach the network (pushing a branch, calling the GitHub
    API). Never appropriate for a phase whose job is to check other work."""


#: Provider-neutral level -> the value `codex exec --sandbox` expects.
CODEX_SANDBOX_FLAGS: dict[PhaseSandbox, str] = {
    PhaseSandbox.READ_ONLY: "read-only",
    PhaseSandbox.WORKSPACE_WRITE: "workspace-write",
    PhaseSandbox.FULL_ACCESS: "danger-full-access",
}


DEFAULT_PHASE_SANDBOX: PhaseSandbox = PhaseSandbox.WORKSPACE_WRITE
"""What a phase gets when it declares nothing.

NOT ``READ_ONLY``, and not for want of wanting it. A phase publishes its
deliverable by WRITING a file under ``artifacts/output/``, which the
collector then picks up - so a read-only phase produces no artifact and the
phase after it starves. ``READ_ONLY`` is correct for a verify phase and
becomes usable once a phase can publish its deliverable without writing;
until then it is opt-in and would break the pipeline if defaulted.

Every codex phase used to receive ``danger-full-access`` unconditionally,
which is how a verify phase came to merge, commit and push the change it then
certified (#1161). Defaulting to ``READ_ONLY`` inverts that: a phase that
writes must say so, and a phase that forgets fails loudly at its first write
instead of silently holding more authority than its author intended.

Measured on codex 0.147.0, since the levels do not mean what their names
suggest:

===================  ==========  ============  =========
level                write file  ``git commit``  network
===================  ==========  ============  =========
``workspace-write``  yes         yes           yes
``read-only``        no          no            **yes**
===================  ==========  ============  =========

Network egress survives every level, so the sandbox is a FILESYSTEM control
only. Do not reach for ``workspace-write`` expecting it to contain a phase to
the box - it will not. Restricting egress is the workspace container's job.
"""


REMOVED_INTERACTIVE_PROVIDER: str = "claude-interactive"
"""The provider value of the REMOVED interactive-tmux path.

Deliberately NOT an ``AgentProvider`` member: nothing may route on it. It
exists so workflow parsing can recognise a stale workflow and fail with a
message that names the removal, instead of a generic "unknown provider".
The tmux path was a failed experiment - a send race, a pane-scrape
completion heuristic, and empty observability timelines - and was excised in
favour of the headless docker-exec substrate (``claude -p`` / ``codex exec``).
Do not reintroduce it as a provider.
"""


class UnsupportedPhaseSandboxError(ValueError):
    """A phase names a sandbox level that is not a known ``PhaseSandbox``.

    Rejected rather than defaulted. Defaulting an unrecognised level would
    hand the phase whatever the fallback happens to be, which is how a typo
    in a workflow definition becomes a silent authority change - the same
    class of failure as remapping an unknown provider.
    """

    def __init__(self, sandbox: object, *, phase_id: str | None = None) -> None:
        self.sandbox = sandbox
        self.phase_id = phase_id
        where = f"Phase {phase_id!r}" if phase_id else "This phase"
        known = ", ".join(repr(str(m)) for m in PhaseSandbox)
        super().__init__(
            f"{where} declares agent.sandbox={sandbox!r}, which is not a known "
            f"sandbox level. Known levels, least to most authority: {known}. "
            "A review or verify phase should declare "
            f"'{PhaseSandbox.READ_ONLY}'."
        )


class UnsupportedAgentProviderError(ValueError):
    """A phase names a provider that cannot be executed.

    Raised at the EXECUTION boundary, never during aggregate replay. YAML
    parsing already rejects ``claude-interactive``
    (``PhaseYamlDefinition._reject_removed_provider``), but YAML is not the
    only entry point: templates stored BEFORE the removal are rehydrated
    straight from their historical ``WorkflowTemplateCreated`` events, and
    trigger-, API- and CLI-initiated executions all run from those stored
    templates. Rehydration stays permissive on purpose - an operator must
    still be able to read and fix an old template - so the refusal has to
    happen where execution begins.

    Without it, a stored interactive phase fell through to ``claude -p`` and
    reported an ordinary headless SUCCESS: exactly the silent remap that
    rejecting (rather than remapping) exists to prevent.
    """

    def __init__(self, provider: object, *, phase_id: str | None = None) -> None:
        self.provider = provider
        self.phase_id = phase_id
        super().__init__(_unsupported_provider_message(provider, phase_id))


def _unsupported_provider_message(provider: object, phase_id: str | None) -> str:
    """Build the actionable message carried by ``UnsupportedAgentProviderError``."""
    where = f"Phase {phase_id!r}" if phase_id else "This phase"
    if provider == REMOVED_INTERACTIVE_PROVIDER:
        return (
            f"{where} declares agent.provider={REMOVED_INTERACTIVE_PROVIDER!r}, which has been "
            "removed (ADR-068). The interactive-tmux workspace path no longer exists. This "
            "workflow is REJECTED rather than rerun headless, because it was authored against "
            "an interactive REPL and running it under "
            f"'{AgentProvider.CLAUDE}' would change what the phase does while still reporting "
            "success. Migrate the stored template: set the phase provider to "
            f"'{AgentProvider.CLAUDE}' (claude -p) or '{AgentProvider.CODEX}' (codex exec) and "
            "re-upload the workflow YAML, then execute again."
        )
    supported = ", ".join(f"'{member}'" for member in AgentProvider)
    return (
        f"{where} declares agent.provider={provider!r}, which is not an executable provider. "
        f"Supported providers: {supported}."
    )


def require_executable_provider(
    provider: object,
    *,
    phase_id: str | None = None,
) -> AgentProvider:
    """Return the ``AgentProvider`` named by ``provider``, or raise.

    The single gate every execution-side provider decision goes through. Call
    it BEFORE provisioning a workspace or building an agent command, so an
    unrunnable provider can never reach a container. Deliberately exhaustive:
    a fall-through default (``return claude_command``) is how a removed
    provider silently became a headless Claude run.
    """
    for known in AgentProvider:
        if provider == known:
            return known
    raise UnsupportedAgentProviderError(provider, phase_id=phase_id)


class AgentRunner(StrEnum):
    """Which stream processor drives a headless phase (claude vs codex)."""

    CLAUDE = "claude"
    CODEX = "codex"


_RUNNER_BY_PROVIDER: dict[AgentProvider, AgentRunner] = {
    AgentProvider.CLAUDE: AgentRunner.CLAUDE,
    AgentProvider.CODEX: AgentRunner.CODEX,
}
"""Which stream processor drives each provider. One entry per AgentProvider."""


def runner_for_provider(provider: object, *, phase_id: str | None = None) -> AgentRunner:
    """Return the stream processor for ``provider``, or raise.

    Exhaustive by construction: the lookup is a total mapping over
    ``AgentProvider``, and anything that is not a member never gets that far.
    The previous ``CODEX if is_codex else CLAUDE`` sent every unknown or
    removed provider to the claude parser.
    """
    return _RUNNER_BY_PROVIDER[require_executable_provider(provider, phase_id=phase_id)]


class ModelAlias(StrEnum):
    """CLI-compatible Claude model aliases.

    The ``claude`` CLI resolves these to the latest dated model in each
    family, so the platform stores the alias rather than pinning a version.
    Never write these as bare literals - issue #793.
    """

    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"
    FABLE = "fable"


class ModelId(StrEnum):
    """Canonical model identifiers - the keys of the pricing table.

    An alias (``ModelAlias``) is what a workflow author writes; a ModelId is
    what a price is attached to. Keeping them in separate enums stops the
    two from being used interchangeably, which is how ``"codex"`` - a
    PROVIDER name - once ended up resolving to GPT-5.6 pricing (issue #788).

    Adding a model means adding a member here AND an entry in
    ``syn_shared.pricing.MODEL_PRICING_TABLE``; the table is keyed by this
    enum so a member without a price is a visible gap rather than a silent
    fallback.
    """

    # --- Current generation (ADR-067 phase 0, verified 2026-08-16) ---
    CLAUDE_OPUS_5 = "claude-opus-5"
    CLAUDE_SONNET_5 = "claude-sonnet-5"
    CLAUDE_FABLE_5 = "claude-fable-5"
    CLAUDE_HAIKU_4_5 = "claude-haiku-4-5-20251001"
    GPT_5_6_SOL = "gpt-5.6-sol"
    GPT_5_6_TERRA = "gpt-5.6-terra"
    GPT_5_6_LUNA = "gpt-5.6-luna"
    # --- Previous generation ---
    CLAUDE_OPUS_4_5 = "claude-opus-4-5-20251101"
    CLAUDE_SONNET_4_5 = "claude-sonnet-4-5-20250929"
    # --- Legacy ---
    GPT_5_6 = "gpt-5.6"
    CLAUDE_OPUS_4 = "claude-opus-4-20250514"
    CLAUDE_SONNET_4 = "claude-sonnet-4-20250514"
    CLAUDE_SONNET_3_5 = "claude-3-5-sonnet-20241022"
    CLAUDE_HAIKU_3_5 = "claude-3-5-haiku-20241022"
    CLAUDE_OPUS_3 = "claude-3-opus-20240229"
    CLAUDE_HAIKU_3 = "claude-3-haiku-20240307"


DEFAULT_CLAUDE_MODEL: str = ModelAlias.HAIKU
"""Model a Claude phase runs under when the workflow does not name one.

Haiku keeps unattended/test workflows cheap. This default applies ONLY to
Claude providers: codex does not report its own model on the wire, so a codex
phase without an explicit ``model:`` stays ``None`` (honestly unknown) rather
than inheriting a Claude alias. Synthesizing one is what made every codex run
show up as Haiku in Cost-by-Model - issue #788.

Do not "fix" that by synthesizing the string ``"codex"`` either. An earlier
attempt did, and it propagated as a genuine model id: ``codex exec --model
codex`` names a nonexistent model, and ``resolve_model_pricing("codex")``
confidently returned GPT-5.6 rates for a model we never ran. A confidently
wrong price is invisible in a dashboard; an absent one is at least visibly
missing. ``None`` means "codex ran model-unforced; leave it unpriced until
the real model is known."

Resolution happens in ``AgentConfiguration.__post_init__`` (both copies), NOT
in callers - a caller-side default only covers the paths that caller owns,
which is how the Haiku default survived the first fix.
"""


_CLAUDE_ALIASES: frozenset[str] = frozenset(ModelAlias)


def resolve_phase_model(provider: str, model: str | None) -> str | None:
    """Normalise a phase's model for ``provider``, returning the value to store.

    Both ``AgentConfiguration`` copies call this from ``__post_init__`` so the
    rule lives in exactly one place. Three normalisations, in order:

    1. Blank or whitespace-only means "unset". A workflow with ``model: ""``
       used to be rescued by a caller-side ``phase_model or default``; without
       that, an empty string would reach the CLI as ``--model ""``.
    2. A Claude alias on a CODEX phase is dropped to ``None``. Codex rejects
       Claude models outright, and keeping one is what prices codex runs as
       Haiku (issue #788). This also has to run on ALREADY-RESOLVED input:
       ``dataclasses.replace(claude_config, provider=CODEX)`` re-enters the
       constructor carrying the resolved ``"haiku"``, which no longer looks
       like a default to anything downstream.
    3. An unset model on a non-codex provider gets ``DEFAULT_CLAUDE_MODEL``.

    An explicit non-Claude model is always preserved, so a codex phase that
    names ``gpt-5.6`` keeps it.
    """
    normalised = model.strip() if model is not None else None
    if not normalised:
        normalised = None
    if provider == AgentProvider.CODEX:
        return None if normalised in _CLAUDE_ALIASES else normalised
    return normalised if normalised is not None else DEFAULT_CLAUDE_MODEL
