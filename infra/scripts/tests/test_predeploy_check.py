"""The pre-deploy check must refuse a deploy that would orphan running work (#1179).

These tests drive ``main()`` rather than the internals, because what a deploy
script consumes is the exit code and what an operator consumes is stdout. A
value parsed correctly and then dropped before the report -- at the summary
mapping, the phase lookup or the formatting -- would pass every test that
inspected only the objects on either side of that hop.

The test that matters most is :func:`test_unreachable_api_is_never_reported_as_clear`
and its siblings. A check that answers "nothing running" when it could not
reach the API is worse than no check at all: it converts an unknown into a
confident wrong answer, at exactly the moment (a bad deploy, API already
unhealthy) when work is most likely still in flight.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

import infra.scripts.predeploy_check as predeploy

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

# Values that could not arise from a default, an empty response, or a stub:
# every one of them has to survive the whole path from JSON to stdout.
_EXEC_A = "exec-9191b5ad51ee"
_EXEC_B = "exec-6c33c48ebcfd"
_WORKFLOW = "issue-to-pr-cross-model"
_PHASE = "Make the change"
_DURATION_A = "24m 51s"
_DURATION_B = "19m 3s"


def _summary(execution_id: str, duration_display: str) -> dict[str, object]:
    return {
        "workflow_execution_id": execution_id,
        "workflow_name": _WORKFLOW,
        "status": "running",
        "duration_display": duration_display,
    }


def _detail(phase_name: str = _PHASE) -> dict[str, object]:
    return {
        "phases": [
            {"name": "Prepare the workspace", "status": "completed"},
            {"name": phase_name, "status": "running"},
            {"name": "Verify the change", "status": "pending"},
        ]
    }


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _FakeApi:
    """Serves the two endpoints the check calls, recording every Request.

    ``pages`` is indexed by the ``page`` query parameter, so paging is
    exercised rather than assumed.
    """

    def __init__(
        self,
        *,
        pages: list[list[dict[str, object]]],
        detail: dict[str, object] | Exception | None = None,
    ) -> None:
        self._pages = pages
        self._detail: dict[str, object] | Exception = _detail() if detail is None else detail
        self.calls: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        del timeout
        self.calls.append(request)
        url = request.full_url
        if "/executions?" in url:
            index = int(url.split("page=")[1].split("&")[0]) - 1
            page = self._pages[index] if index < len(self._pages) else []
            return _FakeResponse({"executions": page, "total": 0})
        if isinstance(self._detail, Exception):
            raise self._detail
        return _FakeResponse(self._detail)


class _UnreachableApi:
    """Every request fails, the way it does when the API is down mid-deploy."""

    def __init__(self, failure: Exception) -> None:
        self._failure = failure

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        del request, timeout
        raise self._failure


class _MalformedApi:
    """Reachable, answers 200, but the body is not a readable execution list."""

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        del request, timeout
        return _FakeResponse(self._payload)


def _run(urlopen: _FakeApi | _UnreachableApi | _MalformedApi, argv: list[str] | None = None) -> int:
    with patch.object(predeploy.urllib.request, "urlopen", urlopen):
        return predeploy.main(argv or [])


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A developer's own SYN_API_* must not change what these tests exercise."""
    for name in ("SYN_API_URL", "SYN_API_TOKEN", "SYN_API_USER", "SYN_API_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    yield


# --- (a) executions running: report them, exit non-zero ----------------------


def test_running_executions_are_reported_and_block_the_deploy(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = _run(
        _FakeApi(pages=[[_summary(_EXEC_A, _DURATION_A), _summary(_EXEC_B, _DURATION_B)]])
    )

    assert exit_code == predeploy.EXIT_IN_FLIGHT
    out = capsys.readouterr().out
    assert "2 execution(s) in flight" in out
    # Every field an operator needs to judge the cost has to reach the output.
    for expected in (_EXEC_A, _EXEC_B, _WORKFLOW, _PHASE, _DURATION_A, _DURATION_B):
        assert expected in out, f"{expected!r} was dropped before the report"


def test_phase_comes_from_the_execution_detail_not_the_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The list endpoint carries no phase name; it must be looked up per execution."""
    urlopen = _FakeApi(
        pages=[[_summary(_EXEC_A, _DURATION_A)]], detail=_detail("Verify the change")
    )

    assert _run(urlopen) == predeploy.EXIT_IN_FLIGHT
    assert "Verify the change" in capsys.readouterr().out
    assert any(f"/executions/{_EXEC_A}" in c.full_url for c in urlopen.calls)


def test_unreadable_phase_degrades_but_still_blocks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Knowing an execution runs is safety-critical; naming its phase is not."""
    urlopen = _FakeApi(
        pages=[[_summary(_EXEC_A, _DURATION_A)]],
        detail=urllib.error.URLError("connection reset"),
    )

    assert _run(urlopen) == predeploy.EXIT_IN_FLIGHT
    out = capsys.readouterr().out
    assert _EXEC_A in out
    assert "unknown" in out


def test_more_running_executions_than_one_page_are_all_counted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The API caps page_size at 100; the reported count must not stop there."""
    first = [_summary(f"exec-{i:012x}", _DURATION_A) for i in range(predeploy.PAGE_SIZE)]
    second = [_summary(_EXEC_B, _DURATION_B)]

    assert _run(_FakeApi(pages=[first, second])) == predeploy.EXIT_IN_FLIGHT
    out = capsys.readouterr().out
    assert f"{predeploy.PAGE_SIZE + 1} execution(s) in flight" in out
    assert _EXEC_B in out


# --- (b) nothing running: exit zero and say so -------------------------------


def test_no_running_executions_exits_zero_and_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(_FakeApi(pages=[[]])) == predeploy.EXIT_CLEAR
    assert "Nothing in flight" in capsys.readouterr().out


# --- (c) the override must work, and must be loud ----------------------------


def test_force_proceeds_despite_running_executions_and_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = _run(_FakeApi(pages=[[_summary(_EXEC_A, _DURATION_A)]]), ["--force"])

    assert exit_code == predeploy.EXIT_CLEAR
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "--force" in combined
    assert "PROCEEDING ANYWAY" in combined
    assert "orphaned" in combined
    # The override must not hide what it is overriding.
    assert _EXEC_A in captured.out


def test_the_override_is_not_the_default() -> None:
    """A default that blocks is the whole point; a default that proceeds is not a gate."""
    assert _run(_FakeApi(pages=[[_summary(_EXEC_A, _DURATION_A)]])) == predeploy.EXIT_IN_FLIGHT


# --- (d) an unreachable API must fail loudly, never report "all clear" -------


@pytest.mark.parametrize(
    ("failure", "description"),
    [
        (urllib.error.URLError("Connection refused"), "API down mid-deploy"),
        (urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None), "gateway restarting"),
        (urllib.error.HTTPError("u", 401, "Unauthorized", {}, None), "credentials rejected"),
    ],
)
def test_unreachable_api_is_never_reported_as_clear(
    failure: Exception,
    description: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The most dangerous false negative: "no executions running" when we cannot tell."""

    exit_code = _run(_UnreachableApi(failure))

    assert exit_code == predeploy.EXIT_UNAVAILABLE, f"{description} must not exit 0"
    assert exit_code != predeploy.EXIT_CLEAR
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Cannot determine what is running" in combined
    assert "NOT an all-clear" in combined
    # The exact phrasing of the safe answer must never appear when we do not know.
    assert "Nothing in flight" not in combined
    assert "Safe to deploy" not in combined


@pytest.mark.parametrize(
    "payload",
    [
        {"detail": "Internal Server Error"},  # 200 with the wrong shape
        {"executions": None},
        [],  # a list where an object is required
        "not json at all",
    ],
)
def test_a_response_without_a_readable_execution_list_is_unavailable_not_clear(
    payload: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(_MalformedApi(payload)) == predeploy.EXIT_UNAVAILABLE
    combined = capsys.readouterr()
    assert "Nothing in flight" not in (combined.out + combined.err)


def test_running_executions_raises_rather_than_returning_an_empty_list() -> None:
    """The guarantee is structural: no failure path can produce a count of zero."""

    unreachable = _UnreachableApi(urllib.error.URLError("Connection refused"))
    with (
        patch.object(predeploy.urllib.request, "urlopen", unreachable),
        pytest.raises(predeploy.DrainCheckUnavailable),
    ):
        predeploy.running_executions("http://localhost:8137")


def test_force_can_override_an_unreachable_api_but_names_the_blindness(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Otherwise the only way past a broken API is skipping the check entirely."""

    unreachable = _UnreachableApi(urllib.error.URLError("Connection refused"))

    assert _run(unreachable, ["--force"]) == predeploy.EXIT_CLEAR
    combined = capsys.readouterr()
    assert "without knowing what is running" in (combined.out + combined.err)


# --- configuration reaches the request ---------------------------------------


def test_credentials_from_the_environment_reach_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A header built but not attached would show up only as a 401 in production."""
    monkeypatch.setenv("SYN_API_PASSWORD", "s3cret-not-a-default")
    urlopen = _FakeApi(pages=[[]])

    assert _run(urlopen) == predeploy.EXIT_CLEAR
    # base64("admin:s3cret-not-a-default"), the gateway's own default username.
    assert urlopen.calls[0].get_header("Authorization") == (
        "Basic YWRtaW46czNjcmV0LW5vdC1hLWRlZmF1bHQ="
    )


def test_a_bearer_token_takes_precedence_over_basic_auth() -> None:
    assert (
        predeploy.auth_header_from_env({"SYN_API_TOKEN": "tok-1179", "SYN_API_PASSWORD": "pw"})
        == "Bearer tok-1179"
    )


def test_api_url_from_the_environment_is_what_gets_queried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYN_API_URL", "http://100.114.86.77:8137/")
    urlopen = _FakeApi(pages=[[]])

    assert _run(urlopen) == predeploy.EXIT_CLEAR
    assert urlopen.calls[0].full_url.startswith(
        "http://100.114.86.77:8137/api/v1/executions?status=running"
    )


# --- the property the VPS deploy path depends on -----------------------------


def test_the_check_is_copyable_to_a_host_with_no_repo() -> None:
    """#1179 happened on a VPS with no checkout, no ``just`` and no ``uv``.

    A check that only imports cleanly inside this repo would not have been
    present where the incident occurred, so the standalone property is part of
    the fix rather than an incidental one.
    """
    import ast
    from pathlib import Path

    source = Path(predeploy.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    repo_packages = {"syn_api", "syn_domain", "syn_adapters", "syn_shared", "infra", "infra_config"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level:
            pytest.fail("relative import would break standalone use")

    assert not (imported & repo_packages), (
        f"predeploy_check.py must stay standalone; it imports {imported & repo_packages}"
    )
