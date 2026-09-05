"""`open_pr` must be provisioned without a checkout, and still able to refuse (#1187).

WHAT WAS WRONG. Provisioning was phase-blind. `WorkflowExecutionProcessor`
built one repo list from the workflow and handed it to every phase, and
`SetupPhaseSecrets` cloned whatever it was handed, so `open_pr` -- which reads
one artifact, checks a remote ref and calls `gh pr create` -- paid the same
clone plus recursive submodule init as `implement`, and then never read the
tree it had just cloned. That waste is what this change removes.

NOT "under the shortest budget in the workflow": this docstring used to say
so, and it was wrong. The clone runs in the setup phase under its own
`SYN_SETUP_PHASE_TIMEOUT_SECONDS`; a phase's `timeout_seconds` is handed only
to the agent process, after the workspace exists
(`WorkflowExecutionProcessor.py:633,655`). #1187's ~one-in-three timeouts were
real, but the clone was not what exhausted the 600s, so removing it is not
guaranteed to have fixed them. See `workflows/sdlc/README.md`, "What
`timeout_seconds` actually bounds".

WHY THIS FILE DRIVES THE WHOLE CHAIN. The value starts in `workflow.yaml` and
is only useful at the far end, in the bash the workspace actually executes.
Between the two it crosses `PhaseYamlDefinition`, `PhaseDefinition`, a
serialized `WorkflowTemplateCreated` event, `ExecutablePhase`,
`WorkspaceProvisionHandler` and `SetupPhaseSecrets` -- six hops, each of them
a constructor or a serializer that can drop a field while both ends still look
correct. Asserting `phase.clone_repos is False` would pass with the last four
hops deleted. So the assertions here are on the SETUP SCRIPT and the ARGV,
built from the real workflow file on disk.

WHY THE REFUSAL ASSERTIONS ARE IN THE SAME FILE. The phase's value is that it
declines to open a PR when verification found a blocking defect; it has done
so correctly on real runs. Removing the clone must not remove that, and the
two things it depends on are exactly the two a provisioning change could break:
the verify artifact reaching the workspace, and the refusal instruction
reaching the agent. Neither travels with the clone, but "neither travels with
the clone" is a claim, and this is the file that has to prove it.
"""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from syn_api._wiring import _build_agent_command, _build_workspace_prompt
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
    WorkflowExecutionResult,
)
from syn_shared.env_constants import ENV_CLAUDE_CODE_OAUTH_TOKEN, ENV_GH_REPO, ENV_GITHUB_TOKEN

if TYPE_CHECKING:
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = pytest.mark.unit

#: Resolved from this file, not the process cwd, so moving the workflow fails
#: loudly here instead of silently skipping.
_REPO_ROOT = Path(__file__).resolve().parents[9]
_IMPLEMENT_YAML = _REPO_ROOT / "workflows" / "sdlc" / "implement" / "workflow.yaml"

_REPO_URL = "https://github.com/syntropic137/syntropic137"

#: What a verify phase writes when it finds a release blocker. The point is
#: that this reaches the agent verbatim: the refusal is the agent reading THIS
#: and declining, so a test that injected a bland placeholder would prove
#: nothing about the decision it is supposed to protect.
_BLOCKING_VERIFY_REPORT = """# Verification report

**Verdict: BLOCKING DEFECT.** The migration drops the `session_id` column
before the projection has been rebuilt, so every in-flight execution loses its
attribution. Do not open a PR for this.
"""


class _CapturingProcessor:
    """Reads back the `ExecutablePhase` objects the real handler built.

    Not a shortcut around the processor -- the point is to provision the
    phases production would have provisioned, rather than ones this file
    constructed and could therefore get wrong in the same direction as the
    code under test.
    """

    def __init__(self) -> None:
        self.phases: list[ExecutablePhase] = []

    async def run(
        self,
        *,
        workflow_id: str,
        workflow_name: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, str],
        execution_id: str,
        repos: list[RepositoryRef],
    ) -> WorkflowExecutionResult:
        del workflow_name, inputs, repos
        self.phases = list(phases)
        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status="completed",
            started_at=datetime.now(UTC),
        )


class _WorkflowRepositoryStub:
    def __init__(self, aggregate: WorkflowTemplateAggregate, workflow_id: str) -> None:
        self._aggregate = aggregate
        self._workflow_id = workflow_id

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self._aggregate if aggregate_id == self._workflow_id else None


def _stored_template_after_an_event_round_trip() -> tuple[WorkflowTemplateAggregate, str]:
    """Install the real YAML, then rehydrate it from its own serialized event.

    The round trip is the reason this helper exists rather than returning the
    aggregate `create_workflow` produced. `WorkflowTemplateCreated` is what the
    event store holds, and phases come back out of it as plain dicts fed to
    `PhaseDefinition(**item)`. A field the event does not carry is therefore
    lost silently, on the restart path only -- green tests, wrong behaviour in
    production the next time the API restarts.
    """
    definition = WorkflowDefinition.from_file(_IMPLEMENT_YAML)
    command = build_command_from_definition(definition)

    origin = WorkflowTemplateAggregate()
    origin.create_workflow(command)
    (envelope,) = origin.get_uncommitted_events()
    created = envelope.event

    # Through JSON, not a copy: `model_dump(mode="json")` is what the store
    # persists, so this is the shape rehydration really sees.
    serialized = type(created).model_validate(created.model_dump(mode="json"))

    rehydrated = WorkflowTemplateAggregate()
    rehydrated.apply_event(serialized)
    return rehydrated, definition.id


async def _executable_phases() -> dict[str, ExecutablePhase]:
    """The phases production would run, keyed by id."""
    aggregate, workflow_id = _stored_template_after_an_event_round_trip()
    processor = _CapturingProcessor()
    handler = ExecuteWorkflowHandler(
        processor=processor,  # type: ignore[arg-type]
        workflow_repository=_WorkflowRepositoryStub(aggregate, workflow_id),
    )
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=workflow_id))

    assert [p.phase_id for p in processor.phases] == [
        "bootstrap",
        "implement",
        "verify",
        "open_pr",
    ], "the workflow's phase list changed; these assertions name phases by id"
    return {p.phase_id: p for p in processor.phases}


class _Provisioned:
    """Everything the workspace was actually told to do, for one phase."""

    def __init__(
        self,
        setup_script: str,
        injected: dict[str, bytes],
        argv: list[str],
        agent_env: dict[str, str],
    ) -> None:
        self.setup_script = setup_script
        self.injected = injected
        self.argv = argv
        self.agent_env = agent_env

    @property
    def prompt(self) -> str:
        """The prompt as the agent receives it, whichever harness runs the phase.

        Claude carries it behind ``-p``, read positionally off the flag rather
        than taken as the last element because the tool grant is appended
        after it. Codex - which `verify` runs on - takes it as the trailing
        positional argument instead. Both are the SAME string, one hop past
        the prompt builder, which is the hop worth asserting on.
        """
        if "-p" in self.argv:
            return self.argv[self.argv.index("-p") + 1]
        return self.argv[-1]


async def _provision(phase: ExecutablePhase, *, completed: dict[str, str]) -> _Provisioned:
    """Run the REAL provision handler for one phase against a fake workspace.

    `SetupPhaseSecrets.create` is not patched out: only the GitHub App lookup
    inside it is, so the script under assertion is the one the real code
    builds. Patching the whole class -- which the sibling skills tests do,
    correctly, because they assert on something else -- would replace the
    exact object this change alters.
    """
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1187"
    workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
    workspace.inject_files = AsyncMock()

    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm

    handler = WorkspaceProvisionHandler(
        workspace_service=workspace_service,
        prompt_builder=_build_workspace_prompt,
        command_builder=_build_agent_command,
    )
    todo = TodoItem(
        execution_id="exec-1187",
        action=TodoAction.PROVISION_WORKSPACE,
        phase_id=phase.phase_id,
    )

    with (
        patch(
            "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_github_auth",
            AsyncMock(return_value=({_REPO_URL: "tok-a"}, "syn-bot", "bot@example.com")),
        ),
        patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow.handlers."
            "WorkspaceProvisionHandler._resolve_github_app_token",
            AsyncMock(return_value="tok-a"),
        ),
    ):
        result = await handler.handle(
            todo=todo,
            phase=phase,
            workflow_id="sdlc-implement-v1",
            session_id=f"sess-{phase.phase_id}",
            repos=[_REPO_URL],
            artifacts=ArtifactCollector(AsyncMock(), AsyncMock(), None),
            completed_phase_ids=list(completed),
            phase_outputs=PhaseOutputCache(primary=dict(completed)),
        )

    (secrets,) = workspace.run_setup_phase.call_args.args
    injected = {
        rel_path: content
        for call in workspace.inject_files.call_args_list
        for rel_path, content in call.args[0]
    }
    return _Provisioned(
        secrets.build_setup_script(), injected, result.claude_cmd, dict(result.agent_env)
    )


class TestTheCheckoutIsGoneForOpenPrAndOnlyForOpenPr:
    """The whole chain, from the file on disk to the bash the workspace runs."""

    async def test_open_pr_setup_script_never_clones(self) -> None:
        phases = await _executable_phases()
        provisioned = await _provision(phases["open_pr"], completed={})

        assert "git clone" not in provisioned.setup_script
        assert "submodule update" not in provisioned.setup_script
        assert "/workspace/repos" not in provisioned.setup_script

    async def test_implement_still_clones(self) -> None:
        """The negative control.

        Without it the assertion above passes just as well against a change
        that switched cloning off for every phase, which would break the two
        phases that actually edit code.
        """
        phases = await _executable_phases()
        provisioned = await _provision(phases["implement"], completed={})

        assert "git clone" in provisioned.setup_script
        assert "submodule update --init --recursive" in provisioned.setup_script

    async def test_open_pr_keeps_the_github_credential_its_job_depends_on(self) -> None:
        """No clone is not the same as no GitHub.

        `gh pr create` is the entire point of the phase. The cheap way to skip
        a clone was to pass no repositories, and that would also have dropped
        hosts.yml and the per-repo credential entry -- turning a phase that
        times out sometimes into one that cannot work at all.
        """
        phases = await _executable_phases()
        provisioned = await _provision(phases["open_pr"], completed={})

        assert "~/.config/gh/hosts.yml" in provisioned.setup_script
        assert "oauth_token: tok-a" in provisioned.setup_script
        assert "syntropic137/syntropic137" in provisioned.setup_script

    async def test_no_agents_md_imports_paths_that_were_never_cloned(self) -> None:
        """The synthetic context is @-imports of files under /workspace/repos.

        Injecting it for a phase with no checkout would hand the agent a list
        of paths that do not exist. Claude skips a missing @import silently,
        so nothing would fail - it would just quietly ask for a large file
        that is not there, which is precisely the class of cost this issue is
        about.
        """
        phases = await _executable_phases()
        open_pr = await _provision(phases["open_pr"], completed={})
        implement = await _provision(phases["implement"], completed={})

        assert "AGENTS.md" not in open_pr.injected
        assert "CLAUDE.md" not in open_pr.injected
        assert b"@/workspace/repos/syntropic137/CLAUDE.md" in implement.injected["CLAUDE.md"]


class TestTheRefusalSurvivesTheChange:
    """A verify report naming a blocking defect must still stop the PR.

    Refusal is the agent's decision, and this file cannot make the agent
    decide. What it CAN pin is the two inputs that decision needs, both of
    which pass through the provisioning code this change edits: the report has
    to be in the workspace, and the instruction has to be in the prompt. If
    either is missing the agent cannot refuse for the right reason, whatever
    it happens to do.
    """

    async def test_the_blocking_verify_report_is_in_the_workspace(self) -> None:
        phases = await _executable_phases()
        provisioned = await _provision(
            phases["open_pr"],
            completed={"verify": _BLOCKING_VERIFY_REPORT},
        )

        verify_inputs = {
            path: body
            for path, body in provisioned.injected.items()
            if path.startswith("artifacts/input/verify")
        }
        assert verify_inputs, (
            "the phase was given no verify artifact, so it has nothing to refuse on"
        )
        assert any(b"BLOCKING DEFECT" in body for body in verify_inputs.values())

    async def test_the_refusal_instruction_reaches_the_agent(self) -> None:
        """Asserted on the ARGV, not on the prompt file.

        The prompt is read from disk, substituted, and passed to the command
        builder. Reading `open_pr.md` here would test the file; reading the
        command tests what the agent is actually launched with, which is one
        hop further along and the only one that matters.
        """
        phases = await _executable_phases()
        provisioned = await _provision(
            phases["open_pr"],
            completed={"verify": _BLOCKING_VERIFY_REPORT},
        )

        assert "If verification failed, or found a defect, do not open a PR." in provisioned.prompt

    async def test_the_happy_path_opens_a_pr_from_the_remote_branch_without_pushing(
        self,
    ) -> None:
        """The other side of the gate, and the reason no-clone is coherent.

        The phase is told the branch is already on origin and that it must not
        push. That instruction is what makes a workspace with no working tree
        sufficient: there is nothing to push FROM, and nothing to push. This
        asserts the instruction survives into the launched command, alongside
        the tool grant (`Bash`) the phase needs to call `gh` at all.
        """
        phases = await _executable_phases()
        provisioned = await _provision(
            phases["open_pr"],
            completed={"verify": "# Verification report\n\nVerdict: PASS. No defects.\n"},
        )

        assert "existing remote branch" in provisioned.prompt
        assert "you do not need to push anything" in provisioned.prompt
        assert "Never force push, never rebase." in provisioned.prompt
        # Comma-joined into a single `--tools` value, not one argv element per
        # tool - so this reads the grant the CLI actually parses.
        assert "Bash" in provisioned.argv[provisioned.argv.index("--tools") + 1].split(",")


#: Where `gh` really is, or None. Named once so the guard below and the
#: subprocess call cannot disagree about which binary was checked for.
_GH = shutil.which("gh")

#: `SSL_CERT_FILE` is how `_FakeGitHubApi` becomes trusted, and Go reads it on
#: Linux only - on darwin the system trust store is consulted instead and the
#: variable is ignored, so these tests would fail there for a reason that has
#: nothing to do with the code. Linux is where the workspace image and CI run,
#: which is where the claim needs to hold. `test_the_gh_tests_still_run_where_
#: they_are_true` asserts from outside that this guard has not widened.
_NEEDS_REAL_GH = pytest.mark.skipif(
    sys.platform != "linux" or _GH is None,
    reason=(
        "needs the real `gh` binary, and a Linux host: the fake API is trusted "
        "via SSL_CERT_FILE, which Go honours on Linux and ignores on darwin"
    ),
)


class _FakeGitHubApi:
    """`api.github.com`, served locally, so a real `gh` command can SUCCEED.

    WHY A SERVER AND NOT AN ASSERTION ON AN ERROR MESSAGE. The claim is about
    a consumer: given the configuration provisioning writes, does `gh` target
    the right repository? Only `gh` can answer that, and every
    repository-sensitive `gh` command reaches the API before it will do
    anything - `gh browse --no-browser` HEADs `/repos/OWNER/REPO` first.
    Reading a failure string instead would pass against a `gh` that resolved
    nothing, and a test that reaches the real api.github.com is not a unit
    test.

    HOW `gh` IS REDIRECTED HERE, and what is deliberately NOT touched. Two
    variables Go's HTTP client reads: `HTTPS_PROXY` routes the connection here
    as a CONNECT tunnel, and `SSL_CERT_FILE` makes the certificate minted
    below trusted for `api.github.com`. The provisioned hosts.yml and GH_REPO
    are used verbatim - the host stays `github.com`. That is the point: the
    real generated configuration talking to a fake server, rather than a
    rewritten configuration talking to a real one.

    The interface is two members: `client_env`, and `requests` - the request
    lines that actually arrived, which is what says WHICH repository `gh`
    resolved rather than merely that it resolved one.

    `cryptography` is a dependency of syn-adapters, which the workspace root
    depends on, so it is present wherever this suite runs.
    """

    def __init__(self, directory: Path) -> None:
        self.requests: list[str] = []
        self._ca_file = directory / "fake-github-ca.pem"
        key_file = directory / "fake-github-key.pem"
        self._mint_certificate(self._ca_file, key_file)

        self._tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._tls.load_cert_chain(self._ca_file, key_file)

        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)

    @staticmethod
    def _mint_certificate(cert_file: Path, key_file: Path) -> None:
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.github.com")])
        now = datetime.now(UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("api.github.com")]), critical=False
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )

    @property
    def client_env(self) -> dict[str, str]:
        """What an HTTP client needs to reach this server believing it is GitHub."""
        host, port = self._listener.getsockname()
        return {"HTTPS_PROXY": f"http://{host}:{port}", "SSL_CERT_FILE": str(self._ca_file)}

    def __enter__(self) -> _FakeGitHubApi:
        threading.Thread(target=self._accept_forever, daemon=True).start()
        return self

    def __exit__(self, *_: object) -> None:
        self._listener.close()

    def _accept_forever(self) -> None:
        while True:
            try:
                connection, _ = self._listener.accept()
            except OSError:  # the listener was closed by __exit__
                return
            threading.Thread(target=self._serve, args=(connection,), daemon=True).start()

    def _serve(self, connection: socket.socket) -> None:
        """Answer one CONNECT tunnel, then one request inside it."""
        try:
            if not _read_request_line(connection).startswith("CONNECT "):
                return
            connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            tunnel = self._tls.wrap_socket(connection, server_side=True)
        except (OSError, ssl.SSLError):
            connection.close()
            return

        with tunnel:
            method, _, rest = _read_request_line(tunnel).partition(" ")
            path = rest.split(" ")[0]
            self.requests.append(f"{method} {path}")
            body = b'{"full_name":"syntropic137/syntropic137","default_branch":"main"}'
            tunnel.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + (b"" if method == "HEAD" else body)
            )


def _read_request_line(connection: socket.socket) -> str:
    """The request line of one HTTP message, with its headers consumed."""
    with connection.makefile("rb", buffering=0) as stream:
        request_line = stream.readline().decode(errors="replace").strip()
        while stream.readline() not in (b"\r\n", b"\n", b""):
            pass
    return request_line


def _the_workspace_the_setup_script_leaves_behind(
    setup_script: str, tmp_path: Path
) -> tuple[Path, Path]:
    """Run the generated setup script for real; return its (home, working dir).

    The script is run rather than read because hosts.yml is written by a
    heredoc inside it: pinning the text proves the substring is present, not
    that a file `gh` can parse ends up on disk. The `/workspace` prefix is
    rewritten to a tmpdir because these tests do not run as root; nothing else
    about the script is altered.
    """
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    script_file = tmp_path / "setup.sh"
    script_file.write_text(setup_script.replace("/workspace", str(workspace)))

    completed = subprocess.run(
        ["bash", str(script_file)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            # A unit test must not be able to wait on a human (#1136).
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false",
        },
    )
    assert completed.returncode == 0, completed.stderr
    return home, workspace


def _run_gh(
    args: list[str], *, home: Path, working_directory: Path, agent_env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run `gh` with the provisioned environment and NOTHING else.

    Built from an explicit dict rather than a copy of `os.environ`: the suite
    itself frequently runs inside an agent workspace that already exports
    GH_TOKEN and GH_REPO, and inheriting either would make this test pass
    against a provisioner that injected nothing at all.
    """
    assert _GH is not None
    return subprocess.run(
        [_GH, *args],
        cwd=working_directory,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        stdin=subprocess.DEVNULL,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "NO_COLOR": "1",
            "GH_NO_UPDATE_NOTIFIER": "1",
            "GH_PROMPT_DISABLED": "1",
            **agent_env,
        },
    )


#: The preamble EXACTLY as it read before #1187 made it conditional, copied in
#: rather than imported. A golden re-derived from the code it guards guards
#: nothing: `render_workspace_prompt(clone_repos=True)` would agree with any
#: edit to the cloning branch, which is the one thing this must catch. The
#: pending experiment's baseline is these bytes, so changing them is a decision
#: to invalidate that baseline, and should cost a deliberate edit here.
_THE_PREAMBLE_A_CLONING_PHASE_HAS_ALWAYS_HAD = """\
## Syn137 Workspace Environment

You are an agent running in an ephemeral Docker workspace managed by Syntropic137.

### Workspace Structure

```
/workspace/
├── CLAUDE.md    ← @-imports each repo's CLAUDE.md (loaded automatically)
├── AGENTS.md    ← @-imports each repo's AGENTS.md (same content)
├── artifacts/
│   ├── input/   ← Previous phase outputs (read-only)
│   └── output/  ← Write YOUR deliverables here
└── repos/       ← Pre-cloned repositories (ready to use)
    └── {repo-name}/
```

---

## Critical Rules

1. **Write your actual work to `artifacts/output/`** - this is the ONLY directory collected
2. **NEVER write placeholder text** - no "...", "[Title]", or template text
3. **Every artifact must contain real content** you created for this specific task
4. **Check `artifacts/input/` first** if this is not the first phase

---

## Completing Your Task

### For coding tasks (commits, PRs, code changes):

Your primary deliverable is **code on GitHub**. The artifact is your summary.

1. Navigate to `/workspace/repos/{repo-name}` (repositories are **pre-cloned** — do not run `git clone`), create a feature branch
2. Make changes, commit with clear messages
3. Push to GitHub, create PR if needed
4. Write summary to `artifacts/output/deliverable.md` with:
   - What you actually changed
   - Your actual commit hashes
   - The actual PR URL you created
   - Brief executive summary

### For non-coding tasks (research, analysis, design, planning):

Your primary deliverable is **the content in `artifacts/output/`**.

Write your actual findings, analysis, or plan to `artifacts/output/deliverable.md`.
Structure it appropriately for the task (summary, findings, recommendations, etc.).

---

## Reading Previous Phase Outputs

Check for inputs from previous phases:

```bash
ls /workspace/artifacts/input/
cat /workspace/artifacts/input/*.md
```

Build on this context. If the input contains only placeholder text,
the previous phase failed - report this in your output.

---

## Important

- **Ephemeral workspace** - all files destroyed when session ends
- **Only `artifacts/output/` collected** - everything else is lost
- **Push code before session ends** - unpushed commits are lost
- **Use feature branches** - never push directly to main/master
- **Write REAL content** - never copy example templates literally

---

## Task Result (REQUIRED)

**The very last thing in your response must be a `TASK_RESULT` block.**

If you completed the task successfully:
```
TASK_RESULT: {"success": true, "comments": "Brief summary of what was accomplished"}
```

If you could NOT complete the task (blocked, missing access, error, etc.):
```
TASK_RESULT: {"success": false, "comments": "Specific reason why — what was missing or what failed"}
```

Examples of failure reasons:
- "GitHub App not installed on repo org/repo — cannot clone or push"
- "Repository org/repo does not exist or is not accessible"
- "Pull request #42 was not found"
- "Required environment variable GH_TOKEN is not set"

This is how the orchestrator knows whether to retry, escalate, or mark the task as done."""


class TestThePromptTellsTheTruthAboutCloning:
    """The shared preamble describes the workspace, so it must describe THIS one.

    #1187's merged half made `clone_repos: false` provision credentials without
    a checkout. This preamble still asserted, for every phase, that `repos/`
    held pre-cloned repositories and that step one was to navigate into
    `/workspace/repos/<name>`. Both are false for a no-checkout phase, so the
    gate could not be switched on: turning it on sent the agent into a
    directory that does not exist, on the shortest budget in the workflow.

    Asserted on the provisioned prompt rather than on `render_workspace_prompt`,
    because the flag has one more hop to make after the renderer - `_wiring`
    has to read `phase.clone_repos` and pass it. A renderer that branches
    correctly and a caller that never tells it which branch to take both look
    right from either end.
    """

    async def test_a_cloning_phase_gets_byte_for_byte_the_prompt_it_got_before(self) -> None:
        """The baseline guard. `verify` is the phase a pending experiment measures.

        It sets no `clone_repos`, so it still clones and must still be told the
        repository is pre-cloned. Equality, not a substring check: a baseline
        that tolerates additions is not a baseline.
        """
        phases = await _executable_phases()
        provisioned = await _provision(phases["verify"], completed={})

        preamble, separator, _ = provisioned.prompt.partition("\n\n## Task\n")
        assert separator, "the prompt no longer has a `## Task` section to split on"
        assert preamble == _THE_PREAMBLE_A_CLONING_PHASE_HAS_ALWAYS_HAD

    async def test_a_no_checkout_phase_is_not_told_the_repository_is_on_disk(self) -> None:
        """The whole prompt, not the preamble: `open_pr.md` made the claim too.

        Its "this workspace is a fresh clone" was written when every phase
        cloned, and it is the sentence immediately after the refusal
        instruction - so it is read by an agent deciding whether to open a PR.
        """
        phases = await _executable_phases()
        provisioned = await _provision(
            phases["open_pr"],
            completed={"verify": _BLOCKING_VERIFY_REPORT},
        )

        assert "pre-cloned" not in provisioned.prompt.lower()
        assert "fresh clone" not in provisioned.prompt.lower()
        assert "/workspace/repos" not in provisioned.prompt

    async def test_a_no_checkout_phase_is_told_how_to_work_without_one(self) -> None:
        """Deleting the paragraph would satisfy the test above and help nobody.

        `GH_REPO` is the one that matters. It is provisioned into the agent's
        environment (see the class below), and an environment variable nothing
        mentions is one the agent has no reason to look for - it would reach
        for a working tree instead, and there is not one.
        """
        phases = await _executable_phases()
        provisioned = await _provision(phases["open_pr"], completed={})

        assert "no checkout" in provisioned.prompt
        assert "GH_REPO" in provisioned.prompt
        assert "resolves the repository" in provisioned.prompt


class TestGhCanNameTheRepositoryWithNoCheckoutToInferItFrom:
    """The hop the first cut of #1187 missed, tested at the consumer.

    Removing the clone removed something nobody had noticed was load-bearing.
    `gh` resolves the repository a command targets from the git remotes of the
    surrounding working tree; the checkout supplied that tree as a side
    effect, so repository identity had never been provisioned. With
    `clone_repos: false` there is nothing to infer from, and `gh pr create` -
    the phase's entire job - fails before it makes an API call:

        $ gh pr list --limit 1
        failed to run git: fatal: not a git repository

    The sibling test above asserts hosts.yml exists. That is the assertion
    that let this ship: the credential was fine, and a file existing is not
    its consumer working. These run the real `gh` against the real generated
    configuration instead.
    """

    @_NEEDS_REAL_GH
    async def test_gh_succeeds_and_targets_the_repo_the_phase_was_given(
        self, tmp_path: Path
    ) -> None:
        phases = await _executable_phases()
        provisioned = await _provision(phases["open_pr"], completed={})
        home, workspace = _the_workspace_the_setup_script_leaves_behind(
            provisioned.setup_script, tmp_path
        )

        # (a) There is genuinely nothing for `gh` to infer from - not in the
        # working directory and not in any parent, which is the loophole that
        # would otherwise let the suite's own checkout answer the question.
        assert not any(
            (directory / ".git").exists() for directory in (workspace, *workspace.parents)
        ), f"{workspace} sits under a git tree, so this proves nothing about a no-clone phase"

        # (b) A repository-sensitive operation, run exactly as provisioned.
        with _FakeGitHubApi(tmp_path) as github:
            result = _run_gh(
                ["browse", "--no-browser"],
                home=home,
                working_directory=workspace,
                agent_env={**provisioned.agent_env, **github.client_env},
            )

        assert result.returncode == 0, (
            f"`gh browse` failed with the provisioned configuration: {result.stderr}"
        )
        # (c) The right repository, not merely a repository. Asserted on what
        # reached the server: `gh` cannot have got the answer from anywhere
        # but the environment provisioning built.
        assert github.requests == ["HEAD /repos/syntropic137/syntropic137"]
        assert result.stdout.strip() == "https://github.com/syntropic137/syntropic137"

    @_NEEDS_REAL_GH
    async def test_the_generated_hosts_yml_is_the_credential_that_makes_that_work(
        self, tmp_path: Path
    ) -> None:
        """Without this, hosts.yml could be empty and the test above stays green.

        The provisioned environment also carries GITHUB_TOKEN, and `gh`
        prefers it (#1129). So the file is exercised by taking that token
        away, leaving hosts.yml as the only credential - and the deletion
        control below is what stops THIS test passing on an unauthenticated
        `gh` that never needed a credential at all.
        """
        phases = await _executable_phases()
        provisioned = await _provision(phases["open_pr"], completed={})
        home, workspace = _the_workspace_the_setup_script_leaves_behind(
            provisioned.setup_script, tmp_path
        )
        hosts_yml = home / ".config" / "gh" / "hosts.yml"
        without_token = {
            name: value for name, value in provisioned.agent_env.items() if name != ENV_GITHUB_TOKEN
        }

        with _FakeGitHubApi(tmp_path) as github:
            on_hosts_yml_alone = _run_gh(
                ["browse", "--no-browser"],
                home=home,
                working_directory=workspace,
                agent_env={**without_token, **github.client_env},
            )
            hosts_yml.unlink()
            with_no_credential_at_all = _run_gh(
                ["browse", "--no-browser"],
                home=home,
                working_directory=workspace,
                agent_env={**without_token, **github.client_env},
            )

        assert on_hosts_yml_alone.returncode == 0, on_hosts_yml_alone.stderr
        assert with_no_credential_at_all.returncode != 0, (
            "`gh` succeeded with no credential, so the run above proves nothing "
            "about the generated hosts.yml"
        )

    async def test_a_codex_phase_is_told_the_repository_too(self) -> None:
        """The provider-independence claim, and the one a claude-only fix fails.

        A codex phase gets an EMPTY agent env by design: it authenticates from
        ~/.codex/auth.json and must not be handed claude credentials. So the
        obvious place to put GH_REPO - beside GITHUB_TOKEN in
        `_build_agent_env` - is the one place it must not go, because that
        function does not run for codex at all. Asserted on the real `verify`
        phase, which is the codex phase this workflow ships.
        """
        phases = await _executable_phases()
        verify = await _provision(phases["verify"], completed={})

        assert phases["verify"].agent_config.provider == "codex", (
            "the workflow's verify phase is no longer codex, so this asserts "
            "nothing about the codex path"
        )
        assert verify.agent_env.get(ENV_GH_REPO) == "syntropic137/syntropic137"
        assert ENV_CLAUDE_CODE_OAUTH_TOKEN not in verify.agent_env, (
            "a codex phase must not receive claude credentials; if it now does, "
            "GH_REPO may be arriving via the claude branch and this test has "
            "stopped covering the codex path"
        )


def test_the_gh_tests_still_run_where_they_are_true() -> None:
    """A platform guard is the one fix that cannot fail loudly when it is wrong.

    Widen it by a character - invert the comparison, drop the condition for a
    bare `skip` while chasing a red suite - and the only tests that exercise
    the real `gh` stop running everywhere, including CI, while the file still
    reports green. Nothing else would notice: every other test here passes
    with these two skipped.
    """
    (condition,) = _NEEDS_REAL_GH.mark.args

    assert isinstance(condition, bool), (
        "the gh guard has lost its condition and now skips unconditionally"
    )
    assert not (sys.platform == "linux" and _GH is not None and condition), (
        "the gh guard is skipping on a Linux host that has gh - which is exactly "
        "where the no-working-tree resolution claim has to be checked"
    )
