"""Tests for shared API call helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from syn_cli.commands._api_helpers import (
    api_delete,
    api_get,
    api_get_list,
    api_patch,
    api_post,
    api_put,
    build_params,
    handle_connect_error,
)


def _mock_response(status_code: int = 200, json_data: dict | list | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


def _mock_client(*responses: MagicMock) -> MagicMock:
    client = MagicMock()
    all_responses = list(responses)
    call_idx = {"i": 0}

    def _next(*_a: object, **_kw: object) -> MagicMock:
        idx = call_idx["i"]
        call_idx["i"] += 1
        return all_responses[idx] if idx < len(all_responses) else _mock_response()

    client.get.side_effect = _next
    client.post.side_effect = _next
    client.put.side_effect = _next
    client.patch.side_effect = _next
    client.delete.side_effect = _next
    client.__enter__ = lambda _self: client
    client.__exit__ = MagicMock(return_value=False)
    return client


_CLIENT_PATH = "syn_cli.commands._api_helpers.get_client"


@pytest.mark.unit
class TestHandleConnectError:
    def test_raises_exit(self) -> None:
        with pytest.raises(typer.Exit):
            handle_connect_error()


@pytest.mark.unit
class TestApiGet:
    def test_success(self) -> None:
        client = _mock_client(_mock_response(200, {"key": "value"}))
        with patch(_CLIENT_PATH, return_value=client):
            result = api_get("/test")
        assert result == {"key": "value"}

    def test_error_status(self) -> None:
        client = _mock_client(_mock_response(404, {"detail": "Not found"}))
        with patch(_CLIENT_PATH, return_value=client), pytest.raises(typer.Exit):
            api_get("/test")

    def test_connect_error(self) -> None:
        with patch(_CLIENT_PATH, side_effect=ConnectionError), pytest.raises(typer.Exit):
            api_get("/test")

    def test_params_passed(self) -> None:
        client = _mock_client(_mock_response(200, {}))
        with patch(_CLIENT_PATH, return_value=client):
            api_get("/test", params={"limit": 10})
        client.get.assert_called_once_with("/test", params={"limit": 10})

    def test_custom_expected(self) -> None:
        client = _mock_client(_mock_response(201, {"id": "abc"}))
        with patch(_CLIENT_PATH, return_value=client):
            result = api_get("/test", expected=(200, 201))
        assert result == {"id": "abc"}


@pytest.mark.unit
class TestApiGetList:
    def test_success(self) -> None:
        client = _mock_client(_mock_response(200, [{"id": "1"}, {"id": "2"}]))
        with patch(_CLIENT_PATH, return_value=client):
            result = api_get_list("/test")
        assert result == [{"id": "1"}, {"id": "2"}]


@pytest.mark.unit
class TestApiPost:
    def test_success(self) -> None:
        client = _mock_client(_mock_response(200, {"created": True}))
        with patch(_CLIENT_PATH, return_value=client):
            result = api_post("/test", json={"name": "foo"})
        assert result == {"created": True}

    def test_error_status(self) -> None:
        client = _mock_client(_mock_response(400, {"detail": "Bad request"}))
        with patch(_CLIENT_PATH, return_value=client), pytest.raises(typer.Exit):
            api_post("/test", json={})

    def test_timeout_passed(self) -> None:
        client = _mock_client(_mock_response(200, {}))
        with patch(_CLIENT_PATH, return_value=client):
            api_post("/test", json={"a": 1}, timeout=60.0)
        client.post.assert_called_once_with("/test", json={"a": 1}, timeout=60.0)


@pytest.mark.unit
class TestApiPut:
    def test_success(self) -> None:
        client = _mock_client(_mock_response(200, {"updated": True}))
        with patch(_CLIENT_PATH, return_value=client):
            result = api_put("/test", json={"name": "bar"})
        assert result == {"updated": True}


@pytest.mark.unit
class TestApiPatch:
    def test_success(self) -> None:
        client = _mock_client(_mock_response(200, {"patched": True}))
        with patch(_CLIENT_PATH, return_value=client):
            result = api_patch("/test", json={"action": "pause"})
        assert result == {"patched": True}


@pytest.mark.unit
class TestApiDelete:
    def test_success(self) -> None:
        client = _mock_client(_mock_response(200, {"deleted": True}))
        with patch(_CLIENT_PATH, return_value=client):
            result = api_delete("/test")
        assert result == {"deleted": True}


@pytest.mark.unit
class TestBuildParams:
    def test_filters_none(self) -> None:
        result = build_params(a="1", b=None, c=3)
        assert result == {"a": "1", "c": 3}

    def test_empty(self) -> None:
        result = build_params(x=None, y=None)
        assert result == {}

    def test_all_present(self) -> None:
        result = build_params(limit=50, status="active")
        assert result == {"limit": 50, "status": "active"}
