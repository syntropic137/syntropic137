"""CI and the local gate must run the same checks (#931).

The two were assembled from independent lists and drifted: three checks were
reachable from no local recipe at all, the pre-push hook ran only the THRESHOLD
half of fitness, and a stale generated file could reach CI unnoticed. One push
hit three of those at once.

This makes the drift mechanically impossible to reintroduce: any `just` target
CI invokes must be inside `preflight`'s dependency closure, and every recipe the
justfile defines is either a pre-push gate or says why it is not (#1125).

Recipes are read from `just --dump`, not matched by regex. A regex discovered
gates by NAME (`check-*`, `*-check`), missed any recipe taking parameters
(`check-event-compat *ARGS:`) and never saw an imported `just/*.just` file, so a
gate could be added and wired into nothing while this suite stayed green.
"""

from __future__ import annotations

import functools
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from ci.fitness.conftest import AGENT_WORKSPACE_ENV, pytest_runtest_setup
from pydantic import BaseModel, ConfigDict

pytestmark = pytest.mark.architecture

_ROOT = Path(__file__).resolve().parents[3]
_JUSTFILE = _ROOT / "justfile"
_WORKFLOWS = _ROOT / ".github" / "workflows"

#: The recipes the pre-push hook and the agent workspace gate run. A recipe in
#: the dependency closure of either is a pre-push gate.
_ROOTS = ("preflight", "preflight-agent")

#: Targets CI may invoke directly without being a preflight gate.
_ALLOWED_OUTSIDE: dict[str, str] = {
    "codegen": "preflight runs codegen-check, which invokes it and diffs the result",
    "preflight": "the target itself",
    # Skyline (apps/syn-ui) jobs are path-filtered and outside preflight while it
    # is built out at /next; scripts/check_ci_parity.py RUNNABLE_BUT_EXCLUDED
    # records the same split.
    "skyline-ci": "path-filtered Skyline QA (install, test, build, size budget); run by hand",
    "skyline-e2e": "needs a Playwright browser, which a pre-push hook cannot assume",
    "skyline-screenshots": "Linux Chromium baselines only; macOS fonts differ, so only CI compares",
    "skyline-gateway-smoke": "builds the gateway image, too heavy for a pre-push hook",
    # syntropic137.com (apps/syn-landing): syn-landing.yml is path-filtered like
    # syn-ui.yml, and check_ci_parity.py RUNNABLE_BUT_EXCLUDED records the split.
    "landing-copy-lint": "path-filtered landing copy lint (em dashes); run by hand",
    "landing-colour-lint": "path-filtered landing colour-literal and token-usage lint; run by hand",
    "landing-typecheck": "path-filtered landing tsc --noEmit; run by hand",
    "landing-build": "path-filtered landing vite build; run by hand",
    "landing-lighthouse": "needs Chrome and fetches @lhci/cli, which a pre-push hook cannot assume",
    "landing-energy": "needs a Playwright browser and ~2 minutes of idle measurement",
    # Mutation evidence (#1941). The workflows name these in comments only.
    "mutation-evidence": "dispatches mutation-evidence.yml; a GitHub run, not a local gate",
    "check-no-mutations": "red BY DESIGN while a PR carries .mutations/; see _NOT_A_GATE",
    # Integration evidence (plan 20261015_platform-dispatched-evidence PR 3).
    # integration-evidence.yml names it in a comment only.
    "test-integration-ci": "the full integration suite against real services; not a pre-push gate",
}

_TESTS = "runs tests; qa-ci and CI run the suite, too slow for a static pre-push gate"
_QA_CI_JOB = "builds or tests one app; qa-ci mirrors that CI job, too slow for a pre-push hook"
_SKYLINE = "path-filtered Skyline QA, run by hand or via skyline-ci (see _ALLOWED_OUTSIDE)"
_RUNNING = "probes a RUNNING stack or database, which a pre-push hook has no right to assume"
_LOCAL_ENV = "checks this developer's .env or host, not the committed tree"
_AUDIT = "needs remote advisory data; CI's osv-scan and pip-audit jobs run it"

#: Recipes that CAN fail on a defect but are deliberately not pre-push gates,
#: each with the reason.
_NOT_A_GATE: dict[str, str] = {
    "check-fix": "an auto-fixer, not a check",
    "check-version": "release-time only; a feature branch is expected to differ",
    "changelog-check": "release gate (release-gate.yml); a feature branch is expected to be stale",
    "check-event-compat": (
        "release gate (ADR-072 D9): builds the previous release's syn-domain from "
        "its tag, too heavy for a pre-push hook. No workflow runs it on main either "
        "(found while fixing #1125)"
    ),
    "health-check": _RUNNING,
    "health-json": _RUNNING,
    "health-wait": _RUNNING,
    "validate-events": _RUNNING,
    "predeploy-check": _RUNNING,
    "e2e-smoke": _RUNNING,
    "verify-image-capabilities": "checks a BUILT image for its binaries; the release build runs it",
    "_env-check": _LOCAL_ENV,
    "_selfhost-preflight": _LOCAL_ENV,
    "dev-doctor": _LOCAL_ENV,
    "doctor": _LOCAL_ENV,
    "import-check": "diagnostic helper, not a gate",
    "topology-check": "regenerated by fitness-check, which preflight already runs",
    "check-no-mutations": (
        "fails while a PR carries .mutations/ evidence patches, which is expected "
        "until merge; in preflight the pre-push hook would block pushing them. "
        "ci.yml mutations-not-merged runs it on every PR into main (#1941)"
    ),
    "audit": _AUDIT,
    "deps-audit-py": _AUDIT,
    "deps-audit-npm": _AUDIT,
    "test": _TESTS,
    "test-unit": _TESTS,
    "test-unit-ci": _TESTS,
    "test-cov": _TESTS,
    "test-integration": _TESTS,
    "test-integration-full": _TESTS,
    "test-e2e": _TESTS,
    "test-e2e-container": _TESTS,
    "test-e2e-container-build": _TESTS,
    "fitness-report": "a verbose re-run of fitness-invariants, which preflight already runs",
    "check": "an older sweep of lint, format, typecheck and fitness; preflight runs each directly",
    "qa": "the broad local sweep; it runs tests, which preflight deliberately does not",
    "qa-full": "qa plus coverage; it runs tests, which preflight deliberately does not",
    "qa-ci": "runs preflight itself, then the CI jobs that test and build",
    "validate-pre-merge": "runs tests and E2E; a pre-merge sweep, not a pre-push gate",
    "validate-pre-merge-quick": "runs tests; a pre-merge sweep, not a pre-push gate",
    "docs-sync": "qa's codegen drift check; preflight runs codegen-check for the same drift",
    "cli-node-ci": _QA_CI_JOB,
    "cli-node-qa": _QA_CI_JOB,
    "cli-node-typecheck": _QA_CI_JOB,
    "cli-node-test": _QA_CI_JOB,
    "cli-node-build": _QA_CI_JOB,
    "dashboard-ci": _QA_CI_JOB,
    "dashboard-qa": _QA_CI_JOB,
    "dashboard-lint": _QA_CI_JOB,
    "dashboard-test": _QA_CI_JOB,
    "dashboard-build": _QA_CI_JOB,
    "docs-site-ci": _QA_CI_JOB,
    "docs-site-build": _QA_CI_JOB,
    "openclaw-plugin-ci": _QA_CI_JOB,
    "landing-qa": "path-filtered landing QA; its parts are in _ALLOWED_OUTSIDE",
    "skyline-qa": _SKYLINE,
    "skyline-check": _SKYLINE,
    "skyline-test": _SKYLINE,
    "skyline-build": _SKYLINE,
    "skyline-elements": _SKYLINE,
    "skyline-verify-contracts": _SKYLINE,
    "skyline-e2e-root": _SKYLINE,
    "skyline-mutations": "mutates the Skyline gates to prove they bite; slow, run after touching one",
}

#: Recipes that cannot fail on a defect at all, grouped by what they do. A new
#: recipe joins the group for its kind; a recipe that checks something belongs
#: in a root's closure or in _NOT_A_GATE, never here.
_NOT_A_CHECK: dict[str, frozenset[str]] = {
    "starts, stops or inspects a local stack": frozenset(
        {
            "_dev-compose-cmd",
            "_ensure-env",
            "_webhook-start",
            "_webhook-stop",
            "api-backend",
            "dashboard-frontend",
            "dev",
            "dev-down",
            "dev-fresh",
            "dev-logs",
            "dev-record-webhooks",
            "dev-stop",
            "dev-webhooks",
            "dev-webhooks-logs",
            "docs",
            "feedback-backend",
            "landing-dev",
            "landing-preview",
            "proxy-start",
            "replay-webhooks",
            "skyline-dev",
            "skyline-dev-fixtures",
            "skyline-dev-next",
            "skyline-preview-next",
            "test-stack",
            "test-stack-down",
            "test-stack-logs",
            "test-stack-restart",
            "test-stack-stop",
            "env-down",
            "env-list",
            "env-logs",
            "env-start",
            "env-status",
            "env-stop",
            "env-up",
        }
    ),
    "operates a self-hosted deployment": frozenset(
        {
            "selfhost-down",
            "selfhost-logs",
            "selfhost-reset",
            "selfhost-restart",
            "selfhost-seed",
            "selfhost-status",
            "selfhost-up",
            "selfhost-up-tunnel",
            "selfhost-update",
            "vps-reclaim",
            "apparmor-setup",
            "pit-stop",
            "github-reconfigure",
        }
    ),
    "seeds or migrates a database": frozenset(
        {
            "seed-all",
            "seed-organization",
            "seed-triggers",
            "seed-workflows",
            "feedback-migrate",
        }
    ),
    "installs, syncs, builds or cleans": frozenset(
        {
            "sync",
            "sync-es",
            "lock",
            "update",
            "bump-exclude-newer",
            "dashboard-install",
            "feedback-install",
            "skyline-install",
            "submodules-init",
            "submodules-update",
            "install-hooks",
            "setup-hooks",
            "onboard-dev",
            "new-package",
            "_workspace-check",
            "workspace-build",
            "proxy-build",
            "clean",
        }
    ),
    "generates or rewrites files; a check in preflight diffs the result": frozenset(
        {
            "format",
            "gen-env",
            "gen-compose",
            "docs-cli-gen",
            "docs-regen",
            "generate-llms-txt",
            "changelog",
            "sync-agent-docs",
            "topology",
            "topology-analyze",
            "topology-viz",
        }
    ),
    "cuts or publishes a release": frozenset(
        {
            "bump-version",
            "release-assets",
            "release-local",
            "release-local-full",
            "release-retag",
            "workspace-versions",
        }
    ),
    "manages credentials": frozenset(
        {
            "codex-auth-clip",
            "codex-auth-status",
            "codex-reauth",
            "secrets-delete-token",
            "secrets-store-token",
        }
    ),
    "reports and never fails": frozenset(
        {
            "default",
            "help",
            "deps-tree",
            "test-debt",  # --warn-only; preflight's check-test-debt is the gate
            "security-audit",  # non-blocking by design so `audit` works offline
        }
    ),
}


class _Dependency(BaseModel):
    # extra="ignore", not "forbid": this is `just`'s dump format, which gains
    # fields between releases; only the names below are relied on.
    model_config = ConfigDict(frozen=True, extra="ignore")

    recipe: str


class _Recipe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    dependencies: tuple[_Dependency, ...]
    #: One entry per line; each fragment is literal text or an interpolation.
    body: tuple[tuple[str | list[object], ...], ...]

    @property
    def deps(self) -> list[str]:
        return [d.recipe for d in self.dependencies]

    @property
    def text(self) -> str:
        """The body's literal text; interpolations are dropped."""
        return "\n".join("".join(f for f in line if isinstance(f, str)) for line in self.body)


class _Dump(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    recipes: dict[str, _Recipe]


def _just() -> str:
    just = shutil.which("just")
    if just is None:
        pytest.fail("`just` is not on PATH; every gate that runs this suite needs it")
    return just


@functools.cache
def _recipes(justfile: Path = _JUSTFILE) -> dict[str, _Recipe]:
    """Every recipe `just` itself parses from ``justfile``, imports included."""
    dump = subprocess.run(
        [_just(), "--justfile", str(justfile), "--dump", "--dump-format", "json"],
        cwd=justfile.parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return _Dump.model_validate_json(dump).recipes


def _closure(*roots: str, recipes: dict[str, _Recipe] | None = None) -> set[str]:
    known = _recipes() if recipes is None else recipes
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        current = stack.pop()
        if current in seen or current not in known:
            continue
        seen.add(current)
        stack.extend(known[current].deps)
    return seen


def _excused() -> set[str]:
    return (
        set(_ALLOWED_OUTSIDE)
        | set(_NOT_A_GATE)
        | {name for group in _NOT_A_CHECK.values() for name in group}
    )


def _unaccounted(recipes: dict[str, _Recipe]) -> list[str]:
    """Recipes that are neither a pre-push gate nor excused with a reason."""
    gated = _closure(*_ROOTS, recipes=recipes)
    return sorted(set(recipes) - gated - _excused())


def _ci_just_targets() -> set[str]:
    found: set[str] = set()
    for workflow in _WORKFLOWS.glob("*.y*ml"):
        for name in re.findall(r"just ([a-z][a-z0-9:-]*)", workflow.read_text()):
            found.add(name)
    return found


def test_preflight_exists() -> None:
    assert _recipes()["preflight"].deps, (
        "`preflight` must exist and name the gates; it is the single list "
        "CI, the pre-push hook and AGENTS.md all point at"
    )


def test_every_ci_check_is_reachable_from_preflight() -> None:
    """CI must not invoke a gate that preflight cannot run.

    Weak on its own now that CI calls `just preflight` rather than naming each
    check - which is the point of that change - so
    ``test_every_recipe_is_a_gate_or_says_why_not`` carries the real weight.
    Kept because CI can always add a direct `just <target>` step again.
    """
    covered = _closure("preflight")
    missing = sorted(
        t for t in _ci_just_targets() if t not in covered and t not in _ALLOWED_OUTSIDE
    )

    assert not missing, (
        "CI runs `just` targets that `preflight` does not, so they cannot fail "
        f"before a push: {missing}. Add them to `preflight` in the justfile, or "
        "record why they cannot be local gates in _ALLOWED_OUTSIDE."
    )


def test_every_recipe_is_a_gate_or_says_why_not() -> None:
    """A check nobody runs is worse than no check: it reads as coverage.

    This is the invariant that actually bites. Whatever a new recipe is called
    and whatever parameters it takes, it fails HERE until it is wired into a
    root or classified, at the moment the gap is created rather than months
    later when something slips past it.
    """
    unaccounted = _unaccounted(_recipes())

    assert not unaccounted, (
        f"these recipes are run by neither {' nor '.join(_ROOTS)}: {unaccounted}. "
        "If it can fail on a defect, add it to `preflight-portable` (or `preflight` "
        "if it needs a host tool) or record in _NOT_A_GATE why it cannot be a "
        "pre-push gate. If it checks nothing, add it to its group in _NOT_A_CHECK."
    )


def test_no_classification_is_stale() -> None:
    """An excuse for a recipe that is gone, or that is now a gate, is a lie.

    A stale entry silently pre-excuses whatever reuses the name next.
    """
    recipes = _recipes()
    gated = _closure(*_ROOTS)
    not_a_check = [name for group in _NOT_A_CHECK.values() for name in group]
    classified = [*_NOT_A_GATE, *not_a_check]

    assert not [n for n in _excused() if n not in recipes], (
        f"excused recipes that no longer exist: {sorted(n for n in _excused() if n not in recipes)}"
    )
    assert not set(classified) & gated, (
        f"classified as not a gate, but a root runs them: {sorted(set(classified) & gated)}"
    )
    assert len(classified) == len(set(classified)), (
        "a recipe is classified twice, as a gate and not a check, or in two groups"
    )


def test_discovery_does_not_depend_on_the_name_or_parameters(tmp_path: Path) -> None:
    """The #1125 hole: an orphan named like nothing in particular, taking args.

    Built in a scratch justfile so the real one is untouched; goes through the
    same `_recipes` and `_unaccounted` the invariant above uses.
    """
    justfile = tmp_path / "justfile"
    justfile.write_text(
        "preflight: lint\n\n"
        "preflight-agent: lint\n\n"
        "lint:\n    true\n\n"
        "validate-review-canary *ARGS:\n    false {{ARGS}}\n\n"
        "check-param-canary flag='':\n    false\n"
    )

    assert _unaccounted(_recipes(justfile)) == [
        "check-param-canary",
        "validate-review-canary",
    ]


def test_the_pre_push_hook_delegates_rather_than_listing_its_own_checks() -> None:
    """A hook carrying its own list is how the drift started."""
    hook = _ROOT / ".githooks" / "pre-push"
    if not hook.exists():
        pytest.skip("no pre-push hook in this checkout")
    assert "just preflight" in hook.read_text(), (
        "the pre-push hook must call `just preflight` rather than enumerate checks"
    )


def _commands_run_by(target: str) -> dict[tuple[str, ...], set[tuple[str, str]]]:
    """The argv of every line `just` would execute for ``target``, deps included.

    Read from `just --dry-run`, not from the recipe text, so a line that merely
    MENTIONS a command (``echo just fitness-invariants``) does not count as
    running it. Each argv maps to the env assignments prefixed to it.
    """
    listing = subprocess.run(
        [_just(), "--dry-run", target],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    commands: dict[tuple[str, ...], set[tuple[str, str]]] = {}
    for line in listing.splitlines():
        try:
            words = shlex.split(line)
        except ValueError:
            continue
        env: set[tuple[str, str]] = set()
        while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
            name, _, value = words.pop(0).partition("=")
            env.add((name, value))
        if words:
            commands.setdefault(tuple(words), set()).update(env)
    return commands


def test_preflight_agent_runs_both_halves_of_fitness() -> None:
    """Agents gate on `preflight-agent`; it must run ALL of `fitness`.

    `fitness` is two recipes. #1498 wired in `fitness-check` (the APS
    thresholds) and believed fitness was covered; `fitness-invariants`, the
    `pytest ci/fitness` suite, stayed out, and agent PRs went red on CI for
    deep cross-context imports and untyped projection handlers that their
    local gate never ran (#1562). So this follows each half from
    `preflight-agent` down to the command CI's job ends in.

    `preflight` runs `fitness` itself, so it must NOT also reach the agent
    wrappers, or CI would run each half twice.
    """
    recipes = _recipes()
    agent = _closure("preflight-agent")

    assert "fitness-agent" in agent, "`preflight-agent` no longer runs fitness-check"
    assert "scripts/agent-fitness.sh" in recipes["fitness-agent"].text, (
        "`fitness-agent` must run scripts/agent-fitness.sh, which ends in `just fitness-check`"
    )

    assert "fitness-invariants-agent" in agent, (
        "`preflight-agent` no longer runs the `pytest ci/fitness` invariants"
    )
    assert (AGENT_WORKSPACE_ENV, "1") in _commands_run_by("preflight-agent").get(
        ("just", "fitness-invariants"), set()
    ), (
        "`preflight-agent` must EXECUTE `just fitness-invariants` with "
        f"{AGENT_WORKSPACE_ENV}=1: the `fitness-invariants` recipe itself, not a "
        "copy of its command that can drift from CI's"
    )
    pytest_argv = ("uv", "run", "pytest", "ci/fitness/", "-v", "--tb=short", "-m", "architecture")
    assert pytest_argv in _commands_run_by("fitness-invariants"), (
        "`fitness-invariants` no longer runs the CI pytest command"
    )

    full = _closure("preflight")
    assert {"fitness-check", "fitness-invariants"} <= full
    assert not {"fitness-agent", "fitness-invariants-agent"} & full, (
        "`preflight` would run a fitness half twice"
    )


def test_only_the_agent_gate_lets_a_missing_host_tool_skip() -> None:
    """The skip switch must not reach CI.

    `preflight` and CI promise docker, so there a `host_tool` test with no
    docker must FAIL. If the variable that turns that into a skip leaked into
    any recipe `preflight` runs, CI would go green over checks it never ran.
    """
    setters = {name for name, recipe in _recipes().items() if AGENT_WORKSPACE_ENV in recipe.text}
    assert setters == {"fitness-invariants-agent"}, setters
    assert not setters & _closure("preflight")


class _ItemNeeding:
    """What the skip hook reads from a pytest item: its id and markers."""

    nodeid = "ci/fitness/test_example.py::test_needs_a_tool"

    def __init__(self, tool: str) -> None:
        self._mark = pytest.mark.host_tool(tool).mark

    def iter_markers(self, name: str) -> list[pytest.Mark]:
        return [self._mark] if name == "host_tool" else []


_ABSENT = "syn-no-such-binary-1109"


def test_a_missing_host_tool_skips_as_not_run_in_the_agent_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AGENT_WORKSPACE_ENV, "1")
    with pytest.raises(pytest.skip.Exception, match=f"NOT RUN.*{_ItemNeeding.nodeid}.*`{_ABSENT}`"):
        pytest_runtest_setup(_ItemNeeding(_ABSENT))  # type: ignore[arg-type]


def test_a_missing_host_tool_is_not_skipped_anywhere_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under `preflight` and CI the test runs, and fails on the missing binary."""
    monkeypatch.delenv(AGENT_WORKSPACE_ENV, raising=False)
    try:
        pytest_runtest_setup(_ItemNeeding(_ABSENT))  # type: ignore[arg-type]
    except pytest.skip.Exception as skipped:
        # Letting it escape would mark THIS test skipped, green over the very
        # regression it exists to catch.
        pytest.fail(f"a missing host tool skipped outside the agent gate: {skipped}")
