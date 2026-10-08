"""`scripts/rehearse_upgrade.sh` refuses every unsafe target before it acts (#1769).

A rehearsal restores a production backup, so a rehearsal that reaches the
wrong daemon, project, workdir or credentials can damage production data. The
script is meant to be safe by construction. These tests run the WHOLE script
against a stubbed `docker`, `gh` and `curl` in a throwaway git repository, and
read the stub's command trace to show that each refusal happens before any
compose `create`/`up`, restore or teardown is issued.

`test_removing_a_guard_fails_its_test` deletes each `# guard:<name>` line in
turn and requires the matching scenario's assertion to fail, so every guard is
shown to be the thing its test depends on.

No real Docker runs here; a real local rehearsal is for the orchestrator.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[1] / "rehearse_upgrade.sh"
LOCAL_SOCKET = "unix:///var/run/docker.sock"

DOCKER_STUB = r"""#!/usr/bin/env bash
S=__STATE__
a="$*"; echo "docker ${a//$'\n'/ } | DOCKER_HOST=${DOCKER_HOST-unset} DOCKER_CONTEXT=${DOCKER_CONTEXT-unset}" >> "$S/trace"
case "$1" in
    context) cat "$S/context_host"; exit 0 ;;
    info|cp) exit 0 ;;
    ps) cat "$S/existing_containers" 2>/dev/null; exit 0 ;;
    volume) [ "$2" = ls ] && cat "$S/existing_volumes" 2>/dev/null; exit 0 ;;
    network) [ "$2" = ls ] && cat "$S/existing_networks" 2>/dev/null; exit 0 ;;
    build) [ -f "$S/build_fail" ] && exit 1; exit 0 ;;
    inspect) printf 'PATH=/usr/bin\nANTHROPIC_API_KEY=\nDOCKER_HOST=\nSYN_GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/k\n'
             cat "$S/container_env_extra" 2>/dev/null; exit 0 ;;
    compose) shift ;;
    *) exit 0 ;;
esac
proj=""
while [ $# -gt 0 ]; do case "$1" in -p) proj="$2"; shift 2 ;; --env-file|-f) shift 2 ;; *) break ;; esac; done
case "$1" in
    config)
        vol="${proj}_db_data"; [ -f "$S/config_foreign" ] && vol=syn137_db_data
        src=api_logs; [ -f "$S/config_socket" ] && src=/var/run/docker.sock
        printf '{"services":{"api":{"container_name":"%s-api","volumes":[{"source":"%s"}]}},"volumes":{"db_data":{"name":"%s"}},"networks":{"syn-internal":{"name":"%s_internal"}}}\n' \
            "$proj" "$src" "$vol" "$proj" ;;
    ps) echo "cid-${@: -1}" ;;
    exec)
        sql="${@: -1}"
        case "$sql" in
            *information_schema.tables*)
                n=$(( $(cat "$S/table_queries" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$S/table_queries"
                cat "$S/tables_$n" ;;
            *"coalesce(max(global_nonce)"*) echo "5|5" ;;
            "select count(*) from events") echo 5 ;;
        esac ;;
esac
exit 0
"""

CURL_STUB = r"""#!/usr/bin/env bash
case "${@: -1}" in
    */health|*/api/v1/health) echo '{"subscription":{"status":"live","lag":0,"lagging_projections":[],"held_projections":[],"halted_at":null}}' ;;
    *"/executions?"*) echo '{"total":0,"executions":[],"status_counts":{}}' ;;
    */sessions*) echo '{"total":1}' ;;
    */evals*) echo '{"total":0}' ;;
    *) exit 22 ;;
esac
"""

GH_STUB = r"""#!/usr/bin/env bash
while [ $# -gt 0 ]; do [ "$1" = -D ] && d="$2"; shift; done
mkdir -p "$d"; echo "services: {}" > "$d/docker-compose.syntropic137.yaml"; echo "#!/bin/sh" > "$d/selfhost-entrypoint.sh"
"""

TABLES = 'public.aggregates\t5\npublic.events\t5\npublic.idempotency\t2\nprojections."Session Totals"\t3\n'

# A compose action against the target: anything past the read-only probes.
ACTING = (" create", " up ", " down", " exec ", " restart", " cp ", "pg_restore")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@dataclass
class Rig:
    root: Path
    script: Path = field(init=False)
    state: Path = field(init=False)
    repo: Path = field(init=False)
    dump: Path = field(init=False)

    def __post_init__(self) -> None:
        self.state = self.root / "state"
        self.state.mkdir()
        self.repo = self.root / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "docker" / "init-db").mkdir(parents=True)
        (self.repo / "docker" / "docker-compose.syntropic137.yaml").write_text("services: {}\n")
        (self.repo / "docker" / "selfhost-entrypoint.sh").write_text("#!/bin/sh\n")
        (self.repo / "docker" / "init-db" / "01.sql").write_text("select 1;\n")
        self.script = self.repo / "scripts" / "rehearse_upgrade.sh"
        shutil.copy(SCRIPT, self.script)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
        _git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        _git(self.repo, "tag", "v0.33.1")
        _git(self.root, "clone", "-q", "--bare", str(self.repo), str(self.root / "origin.git"))
        _git(self.repo, "remote", "add", "origin", str(self.root / "origin.git"))
        _git(self.repo, "fetch", "-q", "origin")
        bindir = self.root / "bin"
        bindir.mkdir()
        for name, body in (("docker", DOCKER_STUB), ("curl", CURL_STUB), ("gh", GH_STUB)):
            stub = bindir / name
            stub.write_text(body.replace("__STATE__", str(self.state)))
            stub.chmod(0o755)
        self.bindir = bindir
        self.dump = self.root / "events.dump"
        self.dump.write_bytes(b"PGDMP")
        self.put("context_host", LOCAL_SOCKET)
        self.put("tables_1", TABLES)
        self.put("tables_2", TABLES)

    def put(self, name: str, text: str) -> None:
        (self.state / name).write_text(text)

    def run(
        self, *extra: str, env: dict[str, str] | None = None, workdir: str | None = None
    ) -> Result:
        wd = workdir if workdir is not None else str(self.root / "work")
        args = [
            "bash",
            str(self.script),
            "--dump",
            str(self.dump),
            "--workdir",
            wd,
            "--timeout",
            "5",
            "--to-api-image",
            "api:x",
            "--to-collector-image",
            "col:x",
            *extra,
        ]
        base = {
            "PATH": f"{self.bindir}:{os.environ['PATH']}",
            "HOME": str(self.root),
            "TMPDIR": str(self.root),
        }
        proc = subprocess.run(
            args,
            env={**base, **(env or {})},
            capture_output=True,
            text=True,
            cwd=self.root,
            timeout=120,
        )
        trace_file = self.state / "trace"
        trace = trace_file.read_text().splitlines() if trace_file.exists() else []
        return Result(proc.returncode, proc.stdout + proc.stderr, trace)


@dataclass
class Result:
    rc: int
    output: str
    trace: list[str]

    def acting(self) -> list[str]:
        return [line for line in self.trace if any(a in line.split(" | ")[0] for a in ACTING)]


def assert_refused_before_acting(res: Result, reason: str, *, allow_create: bool = False) -> None:
    assert res.rc == 3, f"expected refusal (3), got {res.rc}\n{res.output}"
    assert "REFUSED: " in res.output and reason in res.output, res.output
    acting = [
        line
        for line in res.acting()
        if not (allow_create and (" create" in line or " down" in line))
    ]
    assert acting == [], f"acted on the target before refusing: {acting}"


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


# --- each unsafe condition: (guard tag, scenario) ---------------------------


def scenario_remote_docker_host(rig: Rig) -> None:
    res = rig.run(env={"DOCKER_HOST": "ssh://root@production.invalid"})
    assert_refused_before_acting(res, "DOCKER_HOST is not a local unix socket")


def scenario_docker_context_env(rig: Rig) -> None:
    res = rig.run(env={"DOCKER_CONTEXT": "production-vps"})
    assert_refused_before_acting(res, "DOCKER_CONTEXT is set")


def scenario_remote_selected_context(rig: Rig) -> None:
    rig.put("context_host", "ssh://root@production.invalid")
    res = rig.run()
    assert_refused_before_acting(res, "endpoint is not a local unix socket")


def scenario_colliding_volume(rig: Rig) -> None:
    rig.put("existing_volumes", "syn137_db_data\nsyn137rehearse-20261001t000000-1_db_data\n")
    assert_refused_before_acting(rig.run(), "already exist")


def scenario_colliding_network(rig: Rig) -> None:
    rig.put("existing_networks", "syn137rehearse-20261001t000000-1_internal\n")
    assert_refused_before_acting(rig.run(), "already exist")


def scenario_colliding_container(rig: Rig) -> None:
    rig.put("existing_containers", "syn137rehearse-20261001t000000-1-api\n")
    assert_refused_before_acting(rig.run(), "already exist")


def scenario_existing_workdir(rig: Rig) -> None:
    existing = rig.root / "install"
    existing.mkdir()
    (existing / ".env").write_text("SENTINEL\n")
    for wd in (str(existing), str(existing) + "/", os.path.relpath(existing, rig.root)):
        res = rig.run(workdir=wd)
        assert_refused_before_acting(res, "already exists")
    assert sorted(p.name for p in existing.iterdir()) == [".env"]
    assert (existing / ".env").read_text() == "SENTINEL\n"


def scenario_symlinked_workdir(rig: Rig) -> None:
    existing = rig.root / "my install"
    existing.mkdir()
    (existing / ".env").write_text("SENTINEL\n")
    (rig.root / "alias").symlink_to(existing)
    (rig.root / "dangling").symlink_to(rig.root / "nowhere")
    for wd in (str(rig.root / "alias"), str(rig.root / "dangling"), str(existing)):
        assert_refused_before_acting(rig.run(workdir=wd), "already exists")
    assert sorted(p.name for p in existing.iterdir()) == [".env"]


def scenario_foreign_rendered_name(rig: Rig) -> None:
    rig.put("config_foreign", "")
    assert_refused_before_acting(rig.run(), "compose names resources outside")


def scenario_docker_socket_mount(rig: Rig) -> None:
    rig.put("config_socket", "")
    assert_refused_before_acting(rig.run(), "mounts a docker socket")


def scenario_credential_in_container(rig: Rig) -> None:
    rig.put(
        "container_env_extra",
        "OP_SERVICE_ACCOUNT_TOKEN_SYNTROPIC137=ops_secretvalue\nSYN_GIT_TOKEN=ghp_secretvalue\n",
    )
    res = rig.run()
    # `create` makes the containers it inspects; nothing may start or restore.
    assert_refused_before_acting(res, "credentials present", allow_create=True)
    assert "OP_SERVICE_ACCOUNT_TOKEN_SYNTROPIC137" in res.output and "SYN_GIT_TOKEN" in res.output
    assert "secretvalue" not in res.output, "a credential value was printed"


SCENARIOS = {
    "docker-host-env": [scenario_remote_docker_host],
    "docker-context-env": [scenario_docker_context_env],
    "docker-context-endpoint": [scenario_remote_selected_context],
    "existing-resources": [
        scenario_colliding_volume,
        scenario_colliding_network,
        scenario_colliding_container,
    ],
    "fresh-workdir": [scenario_existing_workdir, scenario_symlinked_workdir],
    "rendered-names": [scenario_foreign_rendered_name],
    "docker-socket-mount": [scenario_docker_socket_mount],
    "container-credentials": [scenario_credential_in_container],
}
ALL = [(tag, fn) for tag, fns in SCENARIOS.items() for fn in fns]


@pytest.mark.parametrize(("tag", "scenario"), ALL, ids=[fn.__name__ for _, fn in ALL])
def test_unsafe_condition_is_refused_before_acting(rig: Rig, tag: str, scenario: object) -> None:
    scenario(rig)  # type: ignore[operator]


@pytest.mark.parametrize(("tag", "scenario"), ALL, ids=[fn.__name__ for _, fn in ALL])
def test_removing_a_guard_fails_its_test(rig: Rig, tag: str, scenario: object) -> None:
    source = rig.script.read_text().splitlines(keepends=True)
    marker = f"# guard:{tag}"
    kept = [line for line in source if marker not in line]
    assert len(kept) == len(source) - 1, f"exactly one line carries {marker}"
    rig.script.write_text("".join(kept))
    with pytest.raises(AssertionError):
        scenario(rig)  # type: ignore[operator]


def test_project_flag_is_gone(rig: Rig) -> None:
    res = rig.run("--project", "syn137")
    assert res.rc == 2 and res.trace == [], res.output


# --- the safe path ----------------------------------------------------------


def test_safe_path_passes_on_the_pinned_local_daemon_and_cleans_up(rig: Rig) -> None:
    res = rig.run(
        env={
            "ANTHROPIC_API_KEY": "sk-host",
            "SYN_GIT_TOKEN": "ghp-host",
            "OP_SERVICE_ACCOUNT_TOKEN": "ops",
        }
    )
    assert res.rc == 0, res.output
    assert "RESULT: PASS" in res.output
    docker_calls = [line for line in res.trace if not line.startswith("docker context ")]
    # Every call after the probe goes to the pinned local socket, never a context.
    assert all(f"DOCKER_HOST={LOCAL_SOCKET} DOCKER_CONTEXT=unset" in line for line in docker_calls)
    composes = [line for line in res.trace if line.startswith("docker compose")]
    projects = {line.split(" -p ")[1].split()[0] for line in composes}
    assert len(projects) == 1 and next(iter(projects)).startswith("syn137rehearse-")
    assert not any("--remove-orphans" in line for line in res.trace)
    up = next(i for i, line in enumerate(res.trace) if " up " in line)
    create = next(i for i, line in enumerate(res.trace) if " create " in line)
    assert create < up, "container env must be checked before anything starts"
    assert any(" down -v" in line for line in res.trace), "stack not torn down"
    # Host credentials never reach compose: the override pins each to "".
    override = (rig.root / "work" / "override.yaml").read_text()
    for var in (
        "ANTHROPIC_API_KEY",
        "SYN_GIT_TOKEN",
        "OP_SERVICE_ACCOUNT_TOKEN",
        "SYN_SESSION_STORE_AUTH_TOKEN",
    ):
        assert f'      {var}: ""' in override
    assert "public.events" in res.output and 'projections."Session Totals"' in res.output


def test_failed_build_removes_the_worktree_and_its_registration(rig: Rig) -> None:
    wd = rig.root / "work"
    args_without_images = ["--to-api-image", "", "--to-collector-image", ""]
    res = rig.run(*args_without_images)
    assert res.rc != 0, res.output  # the stub repo has no submodules to update
    assert not (wd / "src").exists()
    listed = subprocess.run(
        ["git", "-C", str(rig.repo), "worktree", "list"], capture_output=True, text=True, check=True
    )
    assert str(wd / "src") not in listed.stdout
    assert not any(" up " in line for line in res.trace)


# --- the row-count invariant, through --verify-only ---------------------------


def _verify_only(rig: Rig, before: str, after: str) -> Result:
    out = rig.root / "saved" / "out"
    for label, text in (("from", before), ("to", after)):
        d = out / label
        d.mkdir(parents=True)
        (d / "tables.tsv").write_text(text)
        (d / "events.txt").write_text("5|5\n")
        (d / "executions.json").write_text('{"total":0,"status_counts":{}}')
        (d / "executions.tsv").write_text("")
        (d / "sessions.json").write_text('{"total":1}')
        (d / "evals.json").write_text('{"total":0}')
        (d / "health.json").write_text('{"subscription":{"held_projections":[],"halted_at":null}}')
    (out / "touched-after-baseline.txt").write_text("")
    (out / "spot-ids.txt").write_text("")
    for f in ("from-catchup-seconds", "to-catchup-seconds", "to-api-ready-seconds"):
        (out / f).write_text("0\n")
    proc = subprocess.run(
        ["bash", str(rig.script), "--verify-only", "--workdir", str(rig.root / "saved")],
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"]},
        timeout=60,
    )
    return Result(proc.returncode, proc.stdout + proc.stderr, [])


def _row(output: str, table: str) -> str:
    return next(line for line in output.splitlines() if line.strip().startswith(table + " "))


def test_verify_passes_when_no_table_shrinks(rig: Rig) -> None:
    after = TABLES.replace("public.events\t5", "public.events\t9") + "public.new_projection\t0\n"
    res = _verify_only(rig, TABLES, after)
    assert res.rc == 0, res.output
    assert _row(res.output, "public.new_projection").endswith("ok new table")


@pytest.mark.parametrize(
    ("table", "after", "verdict"),
    [
        (
            "public.aggregates",
            TABLES.replace("public.aggregates\t5", "public.aggregates\t4"),
            "FAIL rows lost",
        ),
        (
            "public.idempotency",
            TABLES.replace("public.idempotency\t2", "public.idempotency\t0"),
            "FAIL rows lost",
        ),
        (
            'projections."Session Totals"',
            TABLES.replace('"Session Totals"\t3', '"Session Totals"\t2'),
            "FAIL rows lost",
        ),
        ("public.idempotency", TABLES.replace("public.idempotency\t2\n", ""), "FAIL table gone"),
    ],
)
def test_verify_fails_on_any_table_losing_rows(
    rig: Rig, table: str, after: str, verdict: str
) -> None:
    res = _verify_only(rig, TABLES, after)
    assert res.rc == 1, res.output
    assert _row(res.output, table).endswith(verdict), res.output
    assert "rows lost or tables gone" in res.output
