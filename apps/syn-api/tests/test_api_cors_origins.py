"""The API's CORS allow-list admits the desktop app's origins (apps/syn-desktop)."""

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from syn_api.config import ApiConfig
from syn_shared.settings.constants import TAURI_DESKTOP_ORIGINS

pytestmark = pytest.mark.unit


def test_tauri_origins_are_the_platform_origins() -> None:
    assert set(TAURI_DESKTOP_ORIGINS) == {"tauri://localhost", "http://tauri.localhost"}


def test_api_config_allows_tauri_origins() -> None:
    origins = ApiConfig.from_env().cors_origins
    for origin in TAURI_DESKTOP_ORIGINS:
        assert origin in origins
    # The existing dev origins are kept.
    assert "http://localhost:5173" in origins


@pytest.mark.parametrize("origin", TAURI_DESKTOP_ORIGINS)
def test_preflight_from_desktop_origin_is_allowed(origin: str) -> None:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ApiConfig.from_env().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    client = TestClient(app)
    res = client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == origin


def test_preflight_from_unknown_origin_is_refused() -> None:
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=ApiConfig.from_env().cors_origins)
    res = TestClient(app).options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in res.headers
