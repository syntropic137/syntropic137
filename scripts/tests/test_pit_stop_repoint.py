"""`pit-stop --stage-only` must stage on a host installed from a release.

A release compose pins syn-api and syn-gateway BY DIGEST, each to its own, and
the stage step used to read only `syn-api:vX`: it aborted with "could not read
the syn-api pin" on every release-installed host (v0.33.2-beta.1, 2026-10-03).
A hotfixed host carries a different tag per service with no registry prefix
(#1431), which a single sed for both services could not repoint either.

These drive the helper through the CLI pit_stop.sh calls, and check its output
with the exact count `--swap-only` prechecks, read out of the script: a stage
that writes something the swap then refuses is the same abort one step later.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_HELPER = _ROOT / "scripts" / "pit_stop_repoint.py"
_SCRIPT = _ROOT / "scripts" / "pit_stop.sh"
_FIXTURES = Path(__file__).parent / "fixtures" / "pit_stop"
_TAG = "v0.33.2-beta.1"


def _stage(
    fixture: str, tmp_path: Path, tag: str = _TAG, *flags: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    staged = tmp_path / "staged.yaml"
    proc = subprocess.run(
        [sys.executable, str(_HELPER), tag, str(_FIXTURES / fixture), str(staged), *flags],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, staged


def _precheck_count(compose: Path, tag: str = _TAG, swapped: str = "api gateway") -> int:
    """Run the `--swap-only` precheck's own `pins_on_tag`, as written in pit_stop.sh."""
    text = _SCRIPT.read_text()
    start = text.index("pins_on_tag() {")
    counter = text[start : text.index("\n}\n", start) + 3]
    proc = subprocess.run(
        [
            "bash",
            "-c",
            f'remote() {{ bash -c "$*"; }}\nTAG={tag}; SWAPPED="{swapped}"\n'
            f"COMPOSE_DIR={compose.parent}; STAGED={compose.name}; TMP={compose.parent}\n"
            f"REPOINT_PY={_SCRIPT.parent / 'pit_stop_repoint.py'}\n{counter}pins_on_tag",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(proc.stdout)


def _image_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if "image:" in line]


class TestStagesEveryPinForm:
    @pytest.mark.parametrize(
        ("fixture", "backup"),
        [
            ("compose-digest.yaml", "sha256-bf783882d031"),
            ("compose-tag.yaml", "v0.33.1-beta.2"),
            ("compose-hotfixed.yaml", "v0.30.0-beta.7-hotfix1046b"),
        ],
    )
    def test_both_services_end_on_the_shipped_ref_and_pass_the_swap_precheck(
        self, fixture: str, backup: str, tmp_path: Path
    ) -> None:
        proc, staged = _stage(fixture, tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == backup
        assert f"image: ghcr.io/syntropic137/syn-api:{_TAG}" in staged.read_text()
        assert f"ghcr.io/syntropic137/syn-gateway:{_TAG}" in staged.read_text()
        assert _precheck_count(staged) == 2

    def test_only_the_two_pins_change(self, tmp_path: Path) -> None:
        """Every other line, including the other digest-pinned images, is byte-identical."""
        _, staged = _stage("compose-digest.yaml", tmp_path)

        before = (_FIXTURES / "compose-digest.yaml").read_text().splitlines()
        after = staged.read_text().splitlines()
        changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
        assert [b.strip() for _, b in changed] == [
            f"image: ghcr.io/syntropic137/syn-api:{_TAG}",
            f"image: ghcr.io/syntropic137/syn-gateway:{_TAG}",
        ]

    def test_the_backup_name_is_filesystem_safe(self, tmp_path: Path) -> None:
        proc, _ = _stage("compose-digest.yaml", tmp_path)

        assert re.fullmatch(r"[0-9A-Za-z._-]+", proc.stdout.strip())


class TestGatewayOnly:
    """`pit_stop.sh --service gateway` (#1310) ships one image, so the stage
    must repoint one pin and leave syn-api on whatever it was deployed from."""

    def test_only_the_gateway_pin_changes(self, tmp_path: Path) -> None:
        proc, staged = _stage("compose-digest.yaml", tmp_path, _TAG, "--service", "gateway")

        assert proc.returncode == 0, proc.stderr
        before = (_FIXTURES / "compose-digest.yaml").read_text().splitlines()
        after = staged.read_text().splitlines()
        changed = [b.strip() for a, b in zip(before, after, strict=True) if a != b]
        assert changed == [f"image: ghcr.io/syntropic137/syn-gateway:{_TAG}"]
        # The one pin a gateway-only swap precheck counts, which is what it requires.
        assert _precheck_count(staged, swapped="gateway") == 1

    def test_the_backup_is_named_for_the_gateway_pin(self, tmp_path: Path) -> None:
        proc, _ = _stage("compose-digest.yaml", tmp_path, _TAG, "--service", "gateway")

        assert proc.stdout.strip() == "sha256-6b416d4a25dd"

    def test_service_all_is_the_default(self, tmp_path: Path) -> None:
        default, staged = _stage("compose-digest.yaml", tmp_path)
        (tmp_path / "all").mkdir()
        explicit, staged_all = _stage(
            "compose-digest.yaml", tmp_path / "all", _TAG, "--service", "all"
        )

        assert (default.stdout, staged.read_text()) == (explicit.stdout, staged_all.read_text())

    @pytest.mark.parametrize("flags", [("--service", "api"), ("--service",), ("--gateway", "x")])
    def test_an_unknown_service_is_a_usage_error(
        self, flags: tuple[str, ...], tmp_path: Path
    ) -> None:
        proc, staged = _stage("compose-digest.yaml", tmp_path, _TAG, *flags)

        assert proc.returncode == 2
        assert not staged.exists()


class TestNothingToStage:
    def test_an_already_staged_file_asks_for_no_backup(self, tmp_path: Path) -> None:
        first, staged = _stage("compose-digest.yaml", tmp_path)
        assert first.returncode == 0
        again = subprocess.run(
            [sys.executable, str(_HELPER), _TAG, str(staged), str(tmp_path / "again.yaml")],
            capture_output=True,
            text=True,
            check=False,
        )

        assert again.returncode == 0, again.stderr
        assert again.stdout.strip() == ""
        assert (tmp_path / "again.yaml").read_text() == staged.read_text()


class TestRefusesToGuess:
    @pytest.mark.parametrize(
        ("compose", "reason"),
        [
            (
                "services:\n  api:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n"
                "  gateway:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n",
                "service api runs ghcr.io/syntropic137/syn-gateway:v1, not syn-api",
            ),
            (
                # Only the executor runs syn-api: there is no `api` service to repoint.
                "services:\n  executor:\n    image: ghcr.io/syntropic137/syn-api:v1\n"
                "  gateway:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n",
                "expected one image line for service api, found 0",
            ),
            (
                "services:\n  api:\n    image: ghcr.io/syntropic137/syn-api:${SYN_VERSION:-latest}\n"
                "  gateway:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n",
                "pinned by a variable",
            ),
            (
                "services:\n  api:\n    image: ghcr.io/syntropic137/syn-api\n"
                "  gateway:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n",
                "not pinned",
            ),
        ],
    )
    def test_an_unrecognised_compose_exits_nonzero_and_writes_nothing(
        self, compose: str, reason: str, tmp_path: Path
    ) -> None:
        deployed = tmp_path / "deployed.yaml"
        deployed.write_text(compose)
        staged = tmp_path / "staged.yaml"

        proc = subprocess.run(
            [sys.executable, str(_HELPER), _TAG, str(deployed), str(staged)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 1
        assert reason in proc.stderr
        assert not staged.exists()


class TestTheExecutorPinIsNeverMoved:
    """A compose with the executor (#1310 1.6) names syn-api twice. A pit stop
    recreates api and gateway only, so the executor's line stays as deployed:
    a pin moved under a container that was never recreated is drift."""

    _OLD_EXECUTOR = "image: ghcr.io/syntropic137/syn-api@sha256:" + "a" * 64
    _SPLIT = (
        "services:\n"
        "  api:\n    image: ghcr.io/syntropic137/syn-api@sha256:" + "b" * 64 + "\n"
        '  executor:\n    profiles: ["run-queue"]\n    ' + _OLD_EXECUTOR + "\n"
        "  gateway:\n    image: ghcr.io/syntropic137/syn-gateway:v1\n"
    )

    @pytest.mark.parametrize("service", ["all", "gateway"])
    def test_no_pit_stop_moves_the_executor_pin_and_the_precheck_still_passes(
        self, tmp_path: Path, service: str
    ) -> None:
        deployed = tmp_path / "deployed.yaml"
        deployed.write_text(self._SPLIT)
        staged = tmp_path / "compose.yaml"

        proc = subprocess.run(
            [sys.executable, str(_HELPER), _TAG, str(deployed), str(staged), "--service", service],
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        api = (
            f"image: ghcr.io/syntropic137/syn-api:{_TAG}"
            if service == "all"
            else "image: ghcr.io/syntropic137/syn-api@sha256:" + "b" * 64
        )
        assert _image_lines(staged) == [
            api,
            self._OLD_EXECUTOR,
            f"image: ghcr.io/syntropic137/syn-gateway:{_TAG}",
        ]
        # The count the stage and --swap-only trust reads the api SERVICE, so
        # the executor's old pin neither fails it nor stands in for api.
        swapped = "api gateway" if service == "all" else "gateway"
        assert _precheck_count(staged, swapped=swapped) == len(swapped.split())

    def test_the_next_stage_over_a_split_api_and_executor_succeeds(self, tmp_path: Path) -> None:
        """The NEXT pit stop finds api and executor on different pins, and
        must not refuse them as two spellings of one image."""
        deployed = tmp_path / "deployed.yaml"
        deployed.write_text(
            "services:\n  api:\n    image: ghcr.io/syntropic137/syn-api:v2\n"
            "  executor:\n    image: ghcr.io/syntropic137/syn-api:v1\n"
            "  gateway:\n    image: ghcr.io/syntropic137/syn-gateway:v2\n"
        )
        staged = tmp_path / "compose.yaml"
        proc = subprocess.run(
            [sys.executable, str(_HELPER), _TAG, str(deployed), str(staged)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert _image_lines(staged)[1] == "image: ghcr.io/syntropic137/syn-api:v1"

    def test_the_executor_on_the_tag_does_not_count_for_api(self, tmp_path: Path) -> None:
        compose = tmp_path / "compose.yaml"
        compose.write_text(
            "services:\n  api:\n    image: ghcr.io/syntropic137/syn-api:v1\n"
            f"  executor:\n    image: ghcr.io/syntropic137/syn-api:{_TAG}\n"
            f"  gateway:\n    image: ghcr.io/syntropic137/syn-gateway:{_TAG}\n"
        )
        assert _precheck_count(compose) == 1


class TestBlankLinesDoNotMoveOwnership:
    """A blank or whitespace-only line above an image key is the same YAML.
    The image-line pattern once matched across it, so `_owner` measured the
    blank line's indent: a valid file was refused, or an executor label named
    `api` was taken for the api service and the executor's pin moved."""

    @staticmethod
    def _release() -> str:
        """The compose the generator publishes, pinned the way a release pins it."""
        sys.path.insert(0, str(_ROOT / "scripts"))
        from generate_published_compose import generate, render

        return render(generate()).replace("${SYN_VERSION:-latest}", "v1")

    @staticmethod
    def _services(path: Path) -> dict[str, dict[str, object]]:
        loaded = yaml.safe_load(path.read_text())
        assert isinstance(loaded, dict)
        services = loaded["services"]
        assert isinstance(services, dict)
        return services

    @pytest.mark.parametrize("gap", ["\n", "  \n", "\n\n"])
    @pytest.mark.parametrize("service", ["api", "gateway"])
    def test_a_blank_line_before_an_image_still_stages(
        self, tmp_path: Path, service: str, gap: str
    ) -> None:
        source = self._release()
        target = f"    image: ghcr.io/syntropic137/syn-{service}:v1"
        assert target in source
        deployed = tmp_path / "deployed.yaml"
        deployed.write_text(source.replace(target, gap + target, 1))
        assert yaml.safe_load(deployed.read_text()) == yaml.safe_load(source)
        staged = tmp_path / "compose.yaml"

        proc = subprocess.run(
            [sys.executable, str(_HELPER), _TAG, str(deployed), str(staged)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        after = self._services(staged)
        for name in ("api", "gateway"):
            assert after[name]["image"] == f"ghcr.io/syntropic137/syn-{name}:{_TAG}"
        assert after["executor"] == self._services(deployed)["executor"]
        assert _precheck_count(staged) == 2

    def test_an_executor_label_named_api_never_owns_the_api_pin(self, tmp_path: Path) -> None:
        source = self._release()
        target = "    image: ghcr.io/syntropic137/syn-api:v1"
        # Other services pin the same image (docker-create-guard), so find
        # each pin by the service that owns it.
        api_at = source.index(target, source.index("\n  api:\n"))
        executor_at = source.index(target, source.index("\n  executor:\n"))
        assert api_at < executor_at
        deployed = tmp_path / "deployed.yaml"
        deployed.write_text(
            source[:api_at]
            + "\n"
            + source[api_at:executor_at]
            + "    labels:\n      api: same-image\n        \n"
            + source[executor_at:]
        )
        before = self._services(deployed)
        assert before["executor"]["labels"] == {"api": "same-image"}
        staged = tmp_path / "compose.yaml"

        proc = subprocess.run(
            [sys.executable, str(_HELPER), _TAG, str(deployed), str(staged)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        after = self._services(staged)
        assert after["executor"]["image"] == "ghcr.io/syntropic137/syn-api:v1"
        assert after["api"]["image"] == f"ghcr.io/syntropic137/syn-api:{_TAG}"
        assert _precheck_count(staged) == 2


def _drift(tmp_path: Path, published: str, deployed: str) -> tuple[int, str]:
    (tmp_path / "published.yaml").write_text(published)
    (tmp_path / "deployed.yaml").write_text(deployed)
    proc = subprocess.run(
        [
            sys.executable,
            str(_HELPER),
            "--drift",
            str(tmp_path / "published.yaml"),
            str(tmp_path / "deployed.yaml"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


class TestDrift:
    """#1511: what the deployed compose lacks of the published one, pins aside."""

    def test_pins_alone_are_not_drift(self, tmp_path: Path) -> None:
        published = (
            "services:\n  api:\n    image: ghcr.io/syntropic137/syn-api:${SYN_VERSION:-latest}\n"
        )
        deployed = f"# release asset\nservices:\n  api:\n    image: ghcr.io/syntropic137/syn-api@sha256:{'a' * 64}\n"
        assert _drift(tmp_path, published, deployed) == (0, "")

    def test_config_the_deployed_file_lacks_is_drift(self, tmp_path: Path) -> None:
        published = (
            "services:\n  api:\n    image: ghcr.io/syntropic137/syn-api:latest\n"
            "    environment:\n      SYN_SESSION_INVENTORY_ARCHIVE_DIR: /app/data/session-inventory\n"
        )
        deployed = "services:\n  api:\n    image: ghcr.io/syntropic137/syn-api:v0.33.0-beta.5\n"
        rc, diff = _drift(tmp_path, published, deployed)
        assert rc == 1
        assert "+      SYN_SESSION_INVENTORY_ARCHIVE_DIR: /app/data/session-inventory\n" in diff

    def test_a_service_on_a_different_image_is_drift(self, tmp_path: Path) -> None:
        published = "services:\n  api:\n    image: ghcr.io/syntropic137/syn-api:latest\n"
        deployed = "services:\n  api:\n    image: ghcr.io/syntropic137/syn-gateway:latest\n"
        assert _drift(tmp_path, published, deployed)[0] == 1


def _add_keys(tmp_path: Path, published: str, deployed: str) -> tuple[int, str, str, Path]:
    (tmp_path / "published.yaml").write_text(published)
    (tmp_path / "deployed.yaml").write_text(deployed)
    out = tmp_path / "keyed.yaml"
    proc = subprocess.run(
        [
            sys.executable,
            str(_HELPER),
            "--add-null-keys",
            str(tmp_path / "published.yaml"),
            str(tmp_path / "deployed.yaml"),
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr, out


_PUBLISHED = (
    "services:\n"
    "  api:\n"
    "    image: ghcr.io/syntropic137/syn-api:${SYN_VERSION:-latest}\n"
    "    environment:\n"
    "      SYN_WORKSPACE_MEMORY_LIMIT_MB: null\n"
    "      SYN_WORKSPACE_MEMORY_MAX_MB: null\n"
    "      SYN_WORKSPACE_CPU_LIMIT: null\n"
    "  executor:\n"
    "    image: ghcr.io/syntropic137/syn-api:${SYN_VERSION:-latest}\n"
    "    environment:\n"
    "      SYN_WORKSPACE_MEMORY_LIMIT_MB: null\n"
    "      SYN_WORKSPACE_MEMORY_MAX_MB: null\n"
    "      SYN_WORKSPACE_CPU_LIMIT: null\n"
)
_DEPLOYED = (
    "# installed from v1.0.5\n"
    "services:\n"
    "  api:\n"
    f"    image: ghcr.io/syntropic137/syn-api@sha256:{'a' * 64}\n"
    "    environment:\n"
    "      SYN_WORKSPACE_MEMORY_LIMIT_MB: null\n"
    "      SYN_WORKSPACE_CPU_LIMIT: null\n"
    "  executor:\n"
    f"    image: ghcr.io/syntropic137/syn-api@sha256:{'b' * 64}\n"
    "    environment:\n"
    "      SYN_WORKSPACE_MEMORY_LIMIT_MB: null\n"
    "      SYN_WORKSPACE_CPU_LIMIT: null\n"
)


class TestAddNullKeys:
    """#2154: added `KEY: null` env passthroughs are the one drift the pit stop
    applies itself; every other difference is still refused, and nothing is written."""

    def test_adds_only_the_missing_null_keys_and_keeps_every_other_byte(
        self, tmp_path: Path
    ) -> None:
        rc, stdout, _, out = _add_keys(tmp_path, _PUBLISHED, _DEPLOYED)
        assert rc == 0
        assert stdout.split() == ["SYN_WORKSPACE_MEMORY_MAX_MB", "SYN_WORKSPACE_MEMORY_MAX_MB"]
        keyed = out.read_text()
        assert _drift(tmp_path, _PUBLISHED, keyed) == (0, "")
        # The host's own comment and digest pins survive; exactly two lines were added.
        assert keyed.splitlines()[0] == "# installed from v1.0.5"
        assert f"syn-api@sha256:{'a' * 64}" in keyed and f"syn-api@sha256:{'b' * 64}" in keyed
        assert len(keyed.splitlines()) == len(_DEPLOYED.splitlines()) + 2
        parsed = yaml.safe_load(keyed)["services"]
        for svc in ("api", "executor"):
            assert parsed[svc]["environment"] == {
                "SYN_WORKSPACE_MEMORY_LIMIT_MB": None,
                "SYN_WORKSPACE_MEMORY_MAX_MB": None,
                "SYN_WORKSPACE_CPU_LIMIT": None,
            }

    def test_running_it_again_adds_nothing(self, tmp_path: Path) -> None:
        _, _, _, out = _add_keys(tmp_path, _PUBLISHED, _DEPLOYED)
        keyed = out.read_text()
        out.unlink()
        rc, stdout, _, out = _add_keys(tmp_path, _PUBLISHED, keyed)
        assert (rc, stdout) == (0, "")
        assert not out.exists()

    @pytest.mark.parametrize(
        "value",
        ['""', "~", "${SYN_WORKSPACE_MEMORY_MAX_MB}", "16384", "null # set me", "'null'"],
    )
    def test_a_key_added_with_anything_but_a_bare_null_is_refused(
        self, tmp_path: Path, value: str
    ) -> None:
        published = _PUBLISHED.replace("SYN_WORKSPACE_MEMORY_MAX_MB: null", f"SYN_WORKSPACE_MEMORY_MAX_MB: {value}")
        rc, stdout, stderr, out = _add_keys(tmp_path, published, _DEPLOYED)
        assert rc == 1 and stdout == "" and "not a KEY: null passthrough" in stderr
        assert not out.exists()

    def test_a_removed_key_is_refused(self, tmp_path: Path) -> None:
        published = _PUBLISHED.replace("      SYN_WORKSPACE_CPU_LIMIT: null\n", "", 1)
        rc, _, stderr, out = _add_keys(tmp_path, published, _DEPLOYED)
        assert rc == 1 and "differs from the published compose" in stderr
        assert not out.exists()

    def test_a_changed_value_is_refused(self, tmp_path: Path) -> None:
        deployed = _DEPLOYED.replace("SYN_WORKSPACE_CPU_LIMIT: null", "SYN_WORKSPACE_CPU_LIMIT: 4", 1)
        rc, _, _, out = _add_keys(tmp_path, _PUBLISHED, deployed)
        assert rc == 1
        assert not out.exists()

    def test_a_null_key_outside_an_environment_map_is_refused(self, tmp_path: Path) -> None:
        labels = "    labels:\n      com.example.role: api\n"
        published = _PUBLISHED.replace("    environment:\n", labels + "    environment:\n", 1).replace(
            "      com.example.role: api\n", "      com.example.role: api\n      SYN_LABEL_ONLY: null\n", 1
        )
        deployed = _DEPLOYED.replace("    environment:\n", labels + "    environment:\n", 1)
        rc, _, stderr, out = _add_keys(tmp_path, published, deployed)
        assert rc == 1 and "SYN_LABEL_ONLY is not in an environment: map" in stderr
        assert not out.exists()

    def test_a_new_service_is_refused(self, tmp_path: Path) -> None:
        published = _PUBLISHED + "  sidecar:\n    image: ghcr.io/syntropic137/syn-sidecar:latest\n"
        rc, _, _, out = _add_keys(tmp_path, published, _DEPLOYED)
        assert rc == 1
        assert not out.exists()

    def test_pins_alone_are_no_drift_and_write_nothing(self, tmp_path: Path) -> None:
        deployed = _PUBLISHED.replace("${SYN_VERSION:-latest}", "v1.0.5")
        rc, stdout, _, out = _add_keys(tmp_path, _PUBLISHED, deployed)
        assert (rc, stdout) == (0, "")
        assert not out.exists()
