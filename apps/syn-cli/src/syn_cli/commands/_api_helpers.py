"""Shared API call helpers — eliminates duplicated error handling across CLI commands."""

from __future__ import annotations

from typing import Any, NoReturn

import typer

from syn_cli._output import console, print_error
from syn_cli.client import get_api_url, get_client


def handle_connect_error() -> NoReturn:
    """Print connection error and exit."""
    print_error(f"Could not connect to API at {get_api_url()}")
    console.print("[dim]Make sure the API server is running.[/dim]")
    raise typer.Exit(1)


def _check_response(
    status_code: int,
    json_data: Any,
    *,
    expected: tuple[int, ...] = (200,),
) -> None:
    """Raise typer.Exit(1) if status code is unexpected."""
    if status_code not in expected:
        detail = (
            json_data.get("detail", f"HTTP {status_code}")
            if isinstance(json_data, dict)
            else f"HTTP {status_code}"
        )
        print_error(str(detail))
        raise typer.Exit(1)


def api_get(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    """GET request with standard error handling. Returns parsed JSON."""
    try:
        with get_client() as client:
            resp = client.get(path, params=params)
    except Exception:
        handle_connect_error()

    data: dict[str, Any] = resp.json()
    _check_response(resp.status_code, data, expected=expected)
    return data


def api_get_list(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
) -> list[Any]:
    """GET request that returns a JSON list. Returns parsed list."""
    try:
        with get_client() as client:
            resp = client.get(path, params=params)
    except Exception:
        handle_connect_error()

    data: list[Any] = resp.json()
    _check_response(resp.status_code, data, expected=expected)
    return data


def api_post(
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
    timeout: float | None = None,
) -> dict[str, Any]:
    """POST request with standard error handling. Returns parsed JSON."""
    try:
        with get_client() as client:
            kwargs: dict[str, Any] = {}
            if json is not None:
                kwargs["json"] = json
            if params is not None:
                kwargs["params"] = params
            if timeout is not None:
                kwargs["timeout"] = timeout
            resp = client.post(path, **kwargs)
    except Exception:
        handle_connect_error()

    data: dict[str, Any] = resp.json()
    _check_response(resp.status_code, data, expected=expected)
    return data


def api_put(
    path: str,
    *,
    json: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    """PUT request with standard error handling. Returns parsed JSON."""
    try:
        with get_client() as client:
            resp = client.put(path, json=json)
    except Exception:
        handle_connect_error()

    data: dict[str, Any] = resp.json()
    _check_response(resp.status_code, data, expected=expected)
    return data


def api_patch(
    path: str,
    *,
    json: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    """PATCH request with standard error handling. Returns parsed JSON."""
    try:
        with get_client() as client:
            resp = client.patch(path, json=json)
    except Exception:
        handle_connect_error()

    data: dict[str, Any] = resp.json()
    _check_response(resp.status_code, data, expected=expected)
    return data


def api_delete(
    path: str,
    *,
    expected: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    """DELETE request with standard error handling. Returns parsed JSON."""
    try:
        with get_client() as client:
            resp = client.delete(path)
    except Exception:
        handle_connect_error()

    data: dict[str, Any] = resp.json()
    _check_response(resp.status_code, data, expected=expected)
    return data


def build_params(**kwargs: Any) -> dict[str, Any]:
    """Build a params dict, filtering out None values."""
    return {k: v for k, v in kwargs.items() if v is not None}
