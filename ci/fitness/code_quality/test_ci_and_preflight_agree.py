"""CI and the local gate must run the same checks (#931), and nothing may hide.

The two were assembled from independent lists and drifted: three checks were
reachable from no local recipe at all, the pre-push hook ran only the THRESHOLD
half of fitness, and a stale generated file could reach CI unnoticed. One push
hit three of those at once.

WHY DISCOVERY IS EXHAUSTIVE (issue #1125). The first version of this file found
gates by NAME - `check-*` or `*-check` - so a gate called anything else was
never examined, and the guard reported full coverage while the gap sat there.
`validate-review-canary` was added during the verify phase of #1113, wired into
nothing, and this file stayed green; renamed to `check-review-canary` it failed
immediately. That is not a hypothetical convention breach either: `lint`,
`typecheck` and `validate-domain-events` are real gates matching neither
pattern, wired in by hand.

A guard whose whole job is noticing what nothing runs cannot be evadable by a
naming choice, so it no longer looks at names. EVERY recipe is now either
inside `preflight`'s closure or classified below. Adding a recipe and wiring it
nowhere fails here whatever you call it.

THE COST, STATED. Every recipe must be classified once, and the two tables
below are that cost paid. They are the repo's usual ratchet-plus-stale-
exception shape: an entry is a decision someone wrote down and a reviewer can
see, and `test_no_classification_entry_is_stale` deletes it for you once it
stops being true. It is not airtight - someone can still put a real gate in
`DOES_NOT_CHECK_ANYTHING` - but that is now a false claim on a diff line rather
than a recipe nobody had to mention.

WHY THE BULK CARRY NO PROSE. `check_ci_parity.py` learned this the hard way:
"a reason that sounds plausible and is wrong is worse than no reason". Ninety
invented sentences would be ninety chances to be confidently wrong, so the
category name is the reason where the category genuinely is the whole reason,
and prose is spent only on the recipes that DO assert something.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest
from scripts.justfile_model import Justfile

pytestmark = pytest.mark.architecture

_ROOT: Final = Path(__file__).resolve().parents[3]
_JUSTFILE: Final = _ROOT / "justfile"
_WORKFLOWS: Final = _ROOT / ".github" / "workflows"

#: The single list CI, the pre-push hook and AGENTS.md all point at.
_GATE: Final = "preflight"

#: Targets CI may invoke directly without being a preflight gate. Empty, and
#: that is the point: it held `codegen` only because the closure used to stop at
#: recipe headers and could not see `codegen-check` running `just codegen` in
#: its body. The model reads bodies now, so the exception is not needed rather
#: than merely satisfied.
_ALLOWED_OUTSIDE: Final[dict[str, str]] = {}

#: Recipes that DO assert something, with why the assertion does not belong in
#: a pre-push gate. These are the classifications worth arguing about, so each
#: carries its own reason.
_CHECKS_BUT_NOT_BEFORE_A_PUSH: Final[dict[str, str]] = {
    # Supersets of preflight: wiring them in would recurse or double-run.
    "check": "lint + format + typecheck + import-check; preflight runs each already",
    "qa": "a superset of preflight",
    "qa-ci": "a superset of preflight; it is what runs preflight plus the builds",
    "qa-full": "a superset of preflight",
    "validate-pre-merge": "a superset of preflight",
    "validate-pre-merge-quick": "a superset of preflight",
    "fitness-report": "verbose rerun of `fitness`, which preflight runs",
    # Tests. preflight is the STATIC half by design; `qa-ci` runs these, and
    # `check-ci-parity` - which preflight DOES run - is what holds that mapping.
    "test": "preflight is the static half; qa-ci runs the tests",
    "test-cov": "preflight is the static half; qa-ci runs the tests",
    "test-debt": "check-test-debt is the gating form, and preflight runs it",
    "test-e2e": "spends real API tokens",
    "test-e2e-container": "provisions a real container; e2e-container.yml owns it",
    "test-e2e-container-build": "rebuilds a multi-gigabyte image first",
    "test-integration": "needs Postgres and Redis, which a hook may not assume",
    "test-integration-full": "starts and stops the test stack",
    "test-unit": "preflight is the static half; qa-ci runs the tests",
    "test-unit-ci": "a qa-ci gate mirroring ci.yml:python-unit-tests",
    "e2e-smoke": "needs the dev stack running",
    # qa-ci gates needing pnpm, which preflight deliberately does not require.
    "cli-node-ci": "a qa-ci gate mirroring ci.yml:cli-node; needs pnpm",
    "cli-node-qa": "cli-node-ci is the gating form",
    "cli-node-test": "cli-node-ci is the gating form",
    "cli-node-typecheck": "cli-node-ci is the gating form",
    "dashboard-ci": "a qa-ci gate mirroring ci.yml:dashboard-ui; needs pnpm",
    "dashboard-lint": "dashboard-ci is the gating form",
    "dashboard-qa": "dashboard-ci is the gating form",
    "docs-site-ci": "a qa-ci gate mirroring ci.yml:docs-site; needs pnpm",
    "docs-sync": "its gating half, check-env-example, is already in preflight",
    # Reach the network, a registry, or a running stack.
    "audit": "queries remote advisory databases",
    "deps-audit-npm": "queries the OSV database; ci.yml:osv-scan owns it",
    "deps-audit-py": "queries the PyPI advisory database; ci.yml:pip-audit owns it",
    "deps-tree": "reports dependency trees; asserts nothing",
    "security-audit": "queries remote advisory databases",
    "health-check": "probes a RUNNING stack, which a pre-push hook has no right to assume",
    "health-json": "the same probe with JSON output",
    "health-wait": "waits on a RUNNING stack",
    "validate-events": "queries a running PostgreSQL",
    "verify-image-capabilities": "inspects a published image; needs a registry",
    "check-version": "release-time only; a feature branch is expected to differ",
    # Report on the machine or the credentials, not on the repository.
    "_env-check": "warns about the local .env; a push cannot break it",
    "_selfhost-preflight": "checks the local machine's Docker and secrets",
    "_workspace-check": "rebuilds the local workspace image when the submodule moved",
    "codex-auth-status": "reports how long a local credential has left",
    "dev-doctor": "reports local .env health",
    "doctor": "reports where each config value came from on this machine",
    "import-check": "diagnostic helper, not a gate",
    # Fixers: they mutate rather than assert. Each has a gating twin above.
    "check-fix": "an auto-fixer, not a check",
    "topology-check": "regenerates topology; preflight already reaches topology-analyze "
    "through fitness-check",
}

#: Recipes that assert nothing at all - they start something, build something,
#: write something, or print something. The category is the whole reason.
_DOES_NOT_CHECK_ANYTHING: Final[frozenset[str]] = frozenset(
    {
        # Run the development stack.
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
        "feedback-backend",
        "feedback-migrate",
        "proxy-build",
        "proxy-start",
        "replay-webhooks",
        "test-stack",
        "test-stack-down",
        "test-stack-logs",
        "test-stack-restart",
        "test-stack-stop",
        # Run an on-demand or self-hosted environment.
        "env-down",
        "env-list",
        "env-logs",
        "env-start",
        "env-status",
        "env-stop",
        "env-up",
        "selfhost-down",
        "selfhost-logs",
        "selfhost-reset",
        "selfhost-restart",
        "selfhost-seed",
        "selfhost-status",
        "selfhost-up",
        "selfhost-up-tunnel",
        "selfhost-update",
        "seed-all",
        "seed-organization",
        "seed-triggers",
        "seed-workflows",
        # Build or publish an artefact.
        "cli-node-build",
        "dashboard-build",
        "docs-site-build",
        "release-assets",
        "release-local",
        "release-local-full",
        "release-retag",
        "workspace-build",
        "workspace-versions",
        # Generate or rewrite a file. Where the file must not drift, the
        # gate is a separate `check-*` recipe that preflight already runs.
        "diagram",
        "docs",
        "docs-gen",
        "docs-regen",
        "format",
        "gen-compose",
        "gen-env",
        "generate-llms-txt",
        "sync-agent-docs",
        "topology",
        "topology-viz",
        # Set up or maintain the checkout and its dependencies.
        "bump-exclude-newer",
        "bump-version",
        "clean",
        "dashboard-install",
        "feedback-install",
        "install-hooks",
        "lock",
        "new-package",
        "onboard-dev",
        "setup-hooks",
        "submodules-init",
        "submodules-update",
        "sync",
        "sync-es",
        "update",
        # Manage credentials and the GitHub App.
        "codex-auth-clip",
        "codex-reauth",
        "github-reconfigure",
        "secrets-delete-token",
        "secrets-store-token",
        # Print something for a human.
        "default",
        "help",
    }
)


def _classified() -> frozenset[str]:
    return frozenset(_CHECKS_BUT_NOT_BEFORE_A_PUSH) | _DOES_NOT_CHECK_ANYTHING


def _unrun(justfile: Justfile, classified: frozenset[str] = frozenset()) -> list[str]:
    """Every recipe `preflight` does not reach and nobody has accounted for."""
    return sorted(justfile.names - justfile.closure(_GATE) - classified)


def _ci_just_targets() -> set[str]:
    """Every recipe a workflow invokes with `just`.

    The name pattern here is a workflow-side filter, not gate discovery: it
    over-approximates on purpose, so a stray match only ever demands MORE of
    preflight. `just "$TARGET"` is the one shape it cannot resolve, and no
    workflow uses it.
    """
    found: set[str] = set()
    for workflow in _WORKFLOWS.glob("*.y*ml"):
        found.update(re.findall(r"\bjust\s+([A-Za-z_][A-Za-z0-9_:-]*)", workflow.read_text()))
    return found


def test_preflight_exists() -> None:
    assert Justfile.load(_JUSTFILE).closure(_GATE) - {_GATE}, (
        "`preflight` must exist and name the gates; it is the single list "
        "CI, the pre-push hook and AGENTS.md all point at"
    )


def test_every_ci_check_is_reachable_from_preflight() -> None:
    """CI must not invoke a gate that preflight cannot run."""
    justfile = Justfile.load(_JUSTFILE)
    covered = justfile.closure(_GATE)
    missing = sorted(
        target
        for target in _ci_just_targets()
        if target in justfile.names and target not in covered and target not in _ALLOWED_OUTSIDE
    )

    assert not missing, (
        "CI runs `just` targets that `preflight` does not, so they cannot fail "
        f"before a push: {missing}. Add them to `preflight` in the justfile, or "
        "record why they cannot be local gates in _ALLOWED_OUTSIDE."
    )


def test_every_recipe_is_a_gate_or_says_why_not() -> None:
    """A check nobody runs is worse than no check: it reads as coverage.

    This is the invariant that actually bites, and it examines every recipe
    rather than the ones whose names announce themselves (#1125).
    """
    unaccounted = _unrun(Justfile.load(_JUSTFILE), _classified())

    assert not unaccounted, (
        f"nothing runs these recipes before a push and nothing says why: {unaccounted}. "
        f"Add each to `{_GATE}` in the justfile; or, if it is not a gate, put it in "
        "_CHECKS_BUT_NOT_BEFORE_A_PUSH with a reason, or in _DOES_NOT_CHECK_ANYTHING "
        "if it asserts nothing at all."
    )


def test_no_classification_entry_is_stale() -> None:
    """An exception nobody deleted is how the last table stopped being true."""
    justfile = Justfile.load(_JUSTFILE)
    classified = _classified()

    gone = sorted(classified - justfile.names)
    assert not gone, f"these classified recipes no longer exist; delete them: {gone}"

    now_wired = sorted(classified & justfile.closure(_GATE))
    assert not now_wired, (
        f"`{_GATE}` runs these, so their classification is dead and misleading: {now_wired}"
    )

    both = sorted(frozenset(_CHECKS_BUT_NOT_BEFORE_A_PUSH) & _DOES_NOT_CHECK_ANYTHING)
    assert not both, f"classified twice, so one of the two reasons is wrong: {both}"


def test_the_pre_push_hook_delegates_rather_than_listing_its_own_checks() -> None:
    """A hook carrying its own list is how the drift started."""
    hook = _ROOT / ".githooks" / "pre-push"
    if not hook.exists():
        pytest.skip("no pre-push hook in this checkout")
    assert "just preflight" in hook.read_text(), (
        "the pre-push hook must call `just preflight` rather than enumerate checks"
    )


def test_the_model_reads_the_justfile_the_way_just_does() -> None:
    """`just` owns the only parser that is right by definition.

    `justfile_model` is hand-written text parsing because the CI job running
    the unit tests has no `just` binary. That is a licence to be wrong in some
    corner, so the real justfile is parsed both ways here and the recipe sets
    and dependency edges must agree. NOT skipped when `just` is absent: this
    test's whole subject is a check that reported success without looking, and
    skipping on missing tooling is that same defect.
    """
    assert shutil.which("just"), (
        "`just` must be installed to run the fitness suite - it is what invokes it"
    )
    dumped = json.loads(
        subprocess.run(
            ["just", "--justfile", str(_JUSTFILE), "--dump", "--dump-format", "json"],
            capture_output=True,
            check=True,
            cwd=_ROOT,
            text=True,
        ).stdout
    )["recipes"]
    justfile = Justfile.load(_JUSTFILE)

    assert set(justfile.names) == set(dumped), (
        "justfile_model and `just` disagree about which recipes exist: "
        f"only the model sees {sorted(set(justfile.names) - set(dumped))}, "
        f"only `just` sees {sorted(set(dumped) - set(justfile.names))}"
    )
    for name, recipe in dumped.items():
        declared = {
            dep["recipe"] if isinstance(dep, dict) else dep for dep in recipe["dependencies"]
        }
        assert declared <= justfile.recipes[name].runs, (
            f"`{name}` depends on {sorted(declared - justfile.recipes[name].runs)}, "
            "which the model did not see"
        )


#: What discovery used to be. Kept as a literal so the reproduction below can
#: show what it misses rather than assert that it did.
_THE_OLD_NAME_RULE: Final = re.compile(r"^(check-[a-z0-9-]+|[a-z0-9-]+-check):", re.MULTILINE)

#: A justfile with one wired gate and three orphans, none of them named like a
#: check: one plain, one reached only through a parameterised recipe, and one
#: reached only from a recipe body. Each is a shape the old discovery could not
#: see, and every one of them is a gate nothing runs.
_ORPHANS = """\
preflight: check-wired
    @echo gate

check-wired:
    @echo wired

validate-review-canary:
    @echo nothing runs me

takes-a-parameter target="all": validate-review-canary
    @echo {{target}}

mentions-in-prose:
    @echo "run just validate-review-canary yourself"
"""


def test_a_gate_named_nothing_like_a_gate_is_still_reported() -> None:
    """#1125: discovery must not depend on the name matching a pattern.

    `validate-review-canary` is the exact recipe the verify phase of #1113 added
    and this file did not notice. The old rule is applied to the same text here
    to show WHY - it finds only the recipe that happened to be called
    `check-wired`, which is already wired in, so it had nothing to report.
    """
    unrun = _unrun(Justfile.parse(_ORPHANS))

    assert set(_THE_OLD_NAME_RULE.findall(_ORPHANS)) == {"check-wired"}, (
        "the old rule is supposed to see only the conventionally named recipe"
    )
    assert "validate-review-canary" in unrun
    assert "takes-a-parameter" in unrun, (
        "a recipe with a parameter is still a recipe; `^name:` never matched one"
    )
    assert "mentions-in-prose" in unrun


def test_naming_a_recipe_in_prose_does_not_count_as_running_it() -> None:
    """The safety-critical half of body scanning.

    Missing a real `just` call only over-reports. Reading a quoted MENTION as a
    call is the direction that loses findings, and the justfile is full of
    `echo "run just dev-logs"`.
    """
    assert (
        "validate-review-canary" not in Justfile.parse(_ORPHANS).recipes["mentions-in-prose"].runs
    )


def test_a_gate_reached_only_from_a_recipe_body_counts_as_run() -> None:
    """`codegen-check` runs `just codegen`; a header-only closure missed that.

    Two exception entries existed to say "actually, something does run this".
    Deleting the blind spot deleted the entries.
    """
    justfile = Justfile.load(_JUSTFILE)
    covered = justfile.closure(_GATE)

    assert "codegen" in covered, "`codegen-check` invokes `just codegen` in its body"
    assert "topology-analyze" in covered, "`fitness-check` invokes it in its body"
    assert "codegen" not in _ALLOWED_OUTSIDE, (
        "the exception saying `codegen-check` runs it was compensating for the "
        "blind spot; the closure sees the invocation now, so it is not needed"
    )
