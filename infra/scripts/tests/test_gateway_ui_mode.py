"""SYN_GATEWAY_UI picks the dashboard the gateway serves at / (docs/syn-ui-rollout.md).

Drives the real entrypoint, as test_gateway_auth_binding.py does, and checks
the generated nginx snippets: ``next`` (default) roots syn-ui at / and turns
/next into a redirect, ``legacy`` restores React at / with syn-ui at /next, and
anything else refuses to start rather than serving a UI nobody asked for.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from syn_shared.settings.infra import GatewayUI, InfraSettings

_GATEWAY_IMAGE = Path(__file__).resolve().parents[3] / "infra" / "docker" / "images" / "gateway"
_ENTRYPOINT = _GATEWAY_IMAGE / "docker-entrypoint.sh"
_NGINX_CONF = _GATEWAY_IMAGE / "nginx.conf"


def _run(tmp_path: Path, ui: str | None) -> tuple[subprocess.CompletedProcess[str], Path]:
    auth_dir = tmp_path / "auth"
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "AUTH_DIR": str(auth_dir)}
    if ui is not None:
        env["SYN_GATEWAY_UI"] = ui
    proc = subprocess.run(
        ["sh", str(_ENTRYPOINT)], capture_output=True, text=True, env=env, check=False
    )
    return proc, auth_dir


@pytest.mark.unit
@pytest.mark.parametrize("ui", [None, "next"])
def test_next_serves_syn_ui_at_root_and_redirects_next(tmp_path: Path, ui: str | None) -> None:
    proc, auth_dir = _run(tmp_path, ui)
    assert proc.returncode == 0, proc.stderr
    assert (auth_dir / "ui-root.conf").read_text().startswith("root /usr/share/nginx/html;")
    locations = (auth_dir / "locations.conf").read_text()
    assert "location = /next {\n    return 301 /;" in locations
    assert "rewrite ^/next/(.*)$ /$1 permanent;" in locations
    assert "try_files $uri $uri/ /index.html;" in locations
    assert "/next/index.html" not in locations


@pytest.mark.unit
def test_legacy_restores_react_at_root_and_syn_ui_at_next(tmp_path: Path) -> None:
    proc, auth_dir = _run(tmp_path, "legacy")
    assert proc.returncode == 0, proc.stderr
    assert (auth_dir / "ui-root.conf").read_text().startswith("root /usr/share/nginx/legacy;")
    locations = (auth_dir / "locations.conf").read_text()
    assert "location = /next {\n    return 301 /next/;" in locations
    assert "try_files $uri $uri/ /next/index.html;" in locations
    assert "permanent;" not in locations


@pytest.mark.unit
@pytest.mark.parametrize("ui", ["Next", "react", ""])
def test_unknown_mode_refuses_to_start(tmp_path: Path, ui: str) -> None:
    proc, _ = _run(tmp_path, ui)
    if ui == "":
        # Empty means unset to the shell's ${VAR:-default}: the default applies.
        assert proc.returncode == 0, proc.stderr
        return
    assert proc.returncode != 0
    assert "SYN_GATEWAY_UI" in proc.stderr


@pytest.mark.unit
def test_api_and_webhook_locations_are_mode_independent(tmp_path: Path) -> None:
    def shared(ui: str) -> str:
        proc, auth_dir = _run(tmp_path / ui, ui)
        assert proc.returncode == 0, proc.stderr
        text = (auth_dir / "locations.conf").read_text()
        return text[: text.index("# Health check")]

    assert shared("next") == shared("legacy")
    assert "location /api/v1/ {" in shared("next")


@pytest.mark.unit
def test_both_listeners_include_the_ui_root() -> None:
    assert _NGINX_CONF.read_text().count("include /tmp/nginx-auth/ui-root.conf;") == 2
    assert "root /usr/share/nginx/html;" not in _NGINX_CONF.read_text()


@pytest.mark.unit
def test_settings_default_matches_the_entrypoint() -> None:
    assert InfraSettings.model_fields["syn_gateway_ui"].default is GatewayUI.NEXT
    assert {m.value for m in GatewayUI} == {"next", "legacy"}
