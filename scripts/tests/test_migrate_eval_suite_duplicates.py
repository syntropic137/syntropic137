"""The one-off duplicate migration, against a fake API holding two launches' evals."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_suite import DEFAULT_SUITE, load_suite
from migrate_eval_suite_duplicates import migrate

_LOADED = load_suite(DEFAULT_SUITE)
_CASE = _LOADED.cases[0]
_V1 = _LOADED.suite.history[0].tag


def _eval(eval_id: str, tags: list[str], pin: str) -> dict[str, object]:
    return {
        "eval_id": eval_id,
        "tags": tags,
        "baseline_repos": [
            {"repository": _LOADED.suite.repository, "requested_ref": pin, "commit_sha": pin}
        ],
    }


class _Api:
    """Case 0 has two pre-v2 evals (one per launch) and no stable eval yet."""

    def __init__(self) -> None:
        self.evals = {
            "dup-a": _eval("dup-a", [_V1, _CASE.tag], _CASE.commit),
            "dup-b": _eval("dup-b", [_V1, _CASE.tag], _CASE.commit),
        }
        self.members = {"dup-a": ["run-1"], "dup-b": ["run-2"]}
        self.writes: list[tuple[str, str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if method != "GET":
            self.writes.append((method, path))
        if method == "GET" and path == "/evals":
            tags = set(request.url.params.get_list("tag"))
            found = [e for e in self.evals.values() if tags <= set(e["tags"])]  # type: ignore[arg-type]
            return httpx.Response(200, json={"evals": found, "total": len(found)})
        if method == "POST" and path == "/evals":
            body = json.loads(request.content)
            self.evals["stable"] = _eval("stable", body["tags"], _CASE.commit)
            self.members["stable"] = []
            return httpx.Response(201, json=self.evals["stable"])
        if method == "GET" and path.endswith("/runs"):
            ids = self.members[path.split("/")[2]]
            items = [{"execution_id": i} for i in ids]
            return httpx.Response(200, json={"items": items, "total": len(ids)})
        if method == "DELETE" and path.endswith("/eval"):
            self.members[request.url.params["eval_id"]].remove(path.split("/")[2])
            return httpx.Response(200, json={})
        if method == "POST" and path.endswith("/eval"):
            self.members[json.loads(request.content)["eval_id"]].append(path.split("/")[2])
            return httpx.Response(200, json={})
        if method == "POST" and path.endswith("/archive"):
            self.evals.pop(path.split("/")[2])
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"detail": path})

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://api", transport=httpx.MockTransport(self.handle))


@pytest.mark.unit
def test_dry_run_changes_nothing_and_says_what_it_would_do() -> None:
    api = _Api()

    lines = migrate(_LOADED, api.client(), dry_run=True)

    assert api.writes == []
    assert f"{_CASE.id}: would archive dup-a" in lines
    assert f"{_CASE.id}: would move run run-2 dup-b -> <new>" in lines


@pytest.mark.unit
def test_duplicates_fold_into_one_stable_eval_and_are_archived() -> None:
    api = _Api()

    migrate(_LOADED, api.client(), dry_run=False)

    assert set(api.evals) == {"stable"}
    assert api.evals["stable"]["tags"] == [_LOADED.suite.suite_tag, _CASE.tag]
    assert sorted(api.members["stable"]) == ["run-1", "run-2"]
    assert migrate(_LOADED, api.client(), dry_run=True) == []
