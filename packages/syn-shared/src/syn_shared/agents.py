"""Shared, type-safe identifiers for workflow phase agents.

These replace bare string literals ("claude" / "codex") that were
previously compared in many places across the domain, adapter, and API
layers. `StrEnum` members compare equal to their string value, so a loose
``provider: str`` field can still be compared against a member
(``provider == AgentProvider.CODEX``) without changing the field type.
"""

from __future__ import annotations

from dataclasses import dataclass
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

    Named provider-neutrally so the same declaration can mean the same thing
    on any harness, but TODAY it steers ``codex exec --sandbox`` only. Claude
    phases scope authority through ``allowed_tools`` and ignore this field -
    declaring ``read-only`` on a claude phase does not restrict it. Do not
    read a level here as a guarantee on a claude phase.

    Ordered least to most authority. Prefer the least a phase can finish
    with: a phase that cannot write cannot invent work it was asked to
    check (#1157, #1161).
    """

    READ_ONLY = "read-only"
    """Read and search only. The correct level for any review, verify or
    audit phase - it makes "the verifier does not modify what it certifies"
    an enforced property rather than a sentence in a prompt.

    Must be declared explicitly; it is not the default (see
    ``DEFAULT_PHASE_SANDBOX`` for why). A phase at this level cannot write
    its deliverable either, so a verify phase moves here only once it has
    another way to publish."""

    WORKSPACE_WRITE = "workspace-write"
    """Read, write and run commands inside the workspace.

    NOT "no network" - network egress was measured as available at every
    level (see ``DEFAULT_PHASE_SANDBOX``). Also NOT usable by a phase that
    publishes a deliverable: this was the v0.28.0-beta.5 default and the
    write under ``artifacts/output/`` was denied (#1167)."""

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


DEFAULT_PHASE_SANDBOX: PhaseSandbox = PhaseSandbox.FULL_ACCESS
"""What a phase gets when it declares nothing: today's behaviour, unchanged.

This is deliberately the MOST permissive level, and that is a stopgap rather
than a judgement that it is correct.

``WORKSPACE_WRITE`` was tried as the default in v0.28.0-beta.5 and broke every
codex phase in production: a phase publishes its deliverable by WRITING under
``artifacts/output/``, the write was denied, no artifact was produced, and the
phase still reported ``completed`` - silently removing the verify gate from
every run (#1167). Rolled back after ~70 minutes.

``READ_ONLY`` is the level a verify phase should run at and is unusable for the
same reason: a read-only phase publishes nothing.

So the default stays where it is until a phase can publish its deliverable
WITHOUT a filesystem write (#1167). That change is what makes ``READ_ONLY``
viable for verify phases, which is the actual goal of #1157 - and it closes
#1161 at the same time, since a verifier that cannot write cannot push the
change it certifies.

What this module still buys today: the level is DECLARED PER PHASE and mapped
at the command builder, instead of a constant hardcoded for every codex phase.
A phase that wants less can ask for less right now.

Levels measured against codex 0.147.0 on macOS. Note the caveat below - these
were NOT measured on Linux, and the sandbox is implemented by the host's native
engine (Seatbelt on macOS, Landlock/seccomp on Linux), so they are indicative
rather than authoritative for the workspace image:

===================  ==========  ==============  =========
level                write file  ``git commit``  network
===================  ==========  ==============  =========
``workspace-write``  yes         yes             yes
``read-only``        no          no              **yes**
===================  ==========  ==============  =========

Network egress survives every level, so the sandbox is a FILESYSTEM control
only. Restricting egress is the workspace container's job, not a flag's.
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

    # --- Current generation (verified 2026-09-24) ---
    CLAUDE_OPUS_5_5 = "claude-opus-5-5"
    GPT_6_SOL = "gpt-6-sol"
    # --- ADR-067 phase 0 generation (verified 2026-08-16) ---
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


class CodexModelAlias(StrEnum):
    """Short model names a workflow author may write on a CODEX phase.

    Codex has no alias feature of its own: ``codex exec --model`` takes a
    concrete slug. These are the platform's aliases, translated to a
    ``ModelId`` by ``resolve_codex_model_alias`` right before ``--model``
    (``syn_api._codex_command``) and by ``MODEL_ALIASES`` for pricing. The
    stored/declared value stays the alias, mirroring how ``opus`` is stored
    for a Claude phase, so a generation swap is one line here.

    Deliberately NOT members of ``ModelAlias``: that enum is Claude-only, and a
    codex phase drops every member of it (issue #788).
    """

    GPT_SOL = "gpt-sol"


CODEX_MODEL_ALIAS_TARGETS: dict[CodexModelAlias, ModelId] = {
    CodexModelAlias.GPT_SOL: ModelId.GPT_6_SOL,
}
"""What each codex alias runs as today. One entry per ``CodexModelAlias``."""


def resolve_codex_model_alias(model: str) -> str:
    """Return the concrete codex slug for ``model``; non-aliases pass through."""
    for alias, target in CODEX_MODEL_ALIAS_TARGETS.items():
        if model == alias:
            return target
    return model


DEFAULT_CLAUDE_MODEL: str = ModelAlias.OPUS
"""Static fallback model for a Claude phase that names none.

This is the LAST-RESORT value, used only when a stored template carries no
model (templates created before defaults were persisted). New templates get
their default at the create/update boundary from ``SYN_DEFAULT_CLAUDE_MODEL``
and PERSIST it in the template event, so changing that setting never rewrites
an existing template on replay. The domain never reads the environment.

Was ``haiku`` (cheap for unattended runs) until 2026-09-24; the owner moved
the default to ``opus`` so an unqualified phase gets the flagship model.
"""


DEFAULT_CODEX_MODEL: str = CodexModelAlias.GPT_SOL
"""Static fallback model for a codex phase that names none.

Same persistence rule as ``DEFAULT_CLAUDE_MODEL``; the setting is
``SYN_DEFAULT_CODEX_MODEL``.

This used to be ``None`` (issue #788), and the reasoning there still holds for
what it rejected: codex does not report its own model on the wire, so the
platform must never SYNTHESIZE a guess at what codex picked. Two guesses were
tried and both were wrong - inheriting the Claude default priced every codex
run as Haiku, and synthesizing the provider name ``"codex"`` produced
``codex exec --model codex`` and GPT-5.6 rates for a model never run.

``gpt-sol`` is not a guess. It is a concrete, priced model that the platform
now FORCES with ``--model gpt-6-sol``, so the requested model is the model that
runs, and the price attached to it is the price of that model. The observed
model (read from the codex rollout, #1284) still wins wherever it exists.
"""


@dataclass(frozen=True)
class PhaseModelDefaults:
    """The per-provider model a phase gets when it declares none.

    Built from settings by the application layer
    (``Settings.phase_model_defaults``) and handed to the template
    create/update handler, which persists the result in the template event.
    Constructing it bare gives the static fallbacks, for tests.
    """

    claude: str = DEFAULT_CLAUDE_MODEL
    codex: str = DEFAULT_CODEX_MODEL

    def for_provider(self, provider: str | None) -> str:
        """Default model for ``provider``. ``None`` means the claude default path."""
        return self.codex if provider == AgentProvider.CODEX else self.claude


_CLAUDE_ALIASES: frozenset[str] = frozenset(ModelAlias)
_CODEX_ALIASES: frozenset[str] = frozenset(CodexModelAlias)


def resolve_phase_model(provider: str, model: str | None) -> str | None:
    """Normalise a phase's model for ``provider``, returning the value to store.

    Both ``AgentConfiguration`` copies call this from ``__post_init__`` so the
    rule lives in exactly one place. Four normalisations, in order:

    1. Blank or whitespace-only means "unset". A workflow with ``model: ""``
       used to be rescued by a caller-side ``phase_model or default``; without
       that, an empty string would reach the CLI as ``--model ""``.
    2. A Claude alias on a CODEX phase is dropped. Codex rejects Claude models
       outright, and keeping one is what priced codex runs as Haiku (issue
       #788). This also has to run on ALREADY-RESOLVED input:
       ``dataclasses.replace(claude_config, provider=CODEX)`` re-enters the
       constructor carrying the resolved ``"opus"``, which no longer looks
       like a default to anything downstream.
    3. Symmetrically, a codex alias on a NON-codex phase is dropped: the
       Claude CLI cannot run ``gpt-sol``, and ``replace(codex_config,
       provider=CLAUDE)`` would otherwise carry the resolved codex default
       across.
    4. An unset (or dropped) model gets the provider's static fallback:
       ``DEFAULT_CODEX_MODEL`` for codex, ``DEFAULT_CLAUDE_MODEL`` otherwise.

    The static fallbacks only matter for templates stored before defaults
    were persisted at the create/update boundary; see ``PhaseModelDefaults``.
    An explicit non-Claude model is always preserved, so a codex phase that
    names ``gpt-5.6`` keeps it.
    """
    normalised = model.strip() if model is not None else None
    if not normalised:
        normalised = None
    if provider == AgentProvider.CODEX:
        if normalised is None or normalised in _CLAUDE_ALIASES:
            return DEFAULT_CODEX_MODEL
        return normalised
    if normalised is None or normalised in _CODEX_ALIASES:
        return DEFAULT_CLAUDE_MODEL
    return normalised
