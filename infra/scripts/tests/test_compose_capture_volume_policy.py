"""The socket proxy must let the API inspect AND remove capture volumes (#1398).

Every workspace session gets a ``syn-capture-<64 hex>`` Docker volume. The API
reaches Docker only through docker-socket-proxy, whose stock rules deny the
``/volumes`` API. Each compose file patches one narrow allow rule into the
proxy's haproxy template. That rule allowed GET only, so ``docker volume rm``
(DELETE) got 403 on every sweep: ``CaptureSpoolRetention`` logged
"Capture spool release failed (RuntimeError)" forever and no capture volume was
ever released, in every deployment. Found by the 2026-10-02 live validation.

This runs the real entrypoint transformation from each compose file against a
template shaped like the proxy's, then evaluates the inserted rule.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = [
    _ROOT / "docker" / "docker-compose.yaml",
    _ROOT / "docker" / "docker-compose.syntropic137.yaml",
]
_VOLUME = "syn-capture-" + "ab" * 32
_TEMPLATE = (
    "frontend dockerfrontend\n    http-request deny unless METH_GET\n    http-request deny\n"
)
_RULE = re.compile(r"http-request allow if \{ method ([A-Z ]+) \} \{ path -m reg (\S+) \}")


def _inserted_rules(compose: Path, tmp_path: Path) -> list[tuple[set[str], re.Pattern[str]]]:
    service = yaml.safe_load(compose.read_text())["services"]["docker-socket-proxy"]
    shell, flags, script = service["entrypoint"][:3]
    template = tmp_path / "haproxy.cfg.template"
    template.write_text(_TEMPLATE)
    # Compose unescapes $$ to $; point the script at our template and stop
    # before it execs the real proxy.
    script = script.replace("$$", "$").replace(
        "/usr/local/etc/haproxy/haproxy.cfg.template", str(template)
    )
    script = script.replace("/tmp/capture-haproxy.template", str(tmp_path / "out.template"))
    script = script.replace('exec /docker-entrypoint.sh "$@"', "true")
    subprocess.run([shell, flags, script], check=True)
    rules = []
    for match in _RULE.finditer(template.read_text()):
        rules.append((set(match.group(1).split()), re.compile(match.group(2))))
    return rules


def _allowed(rules: list[tuple[set[str], re.Pattern[str]]], method: str, path: str) -> bool:
    return any(method in methods and pattern.search(path) for methods, pattern in rules)


@pytest.mark.parametrize("compose", _COMPOSE, ids=lambda p: p.name)
class TestCaptureVolumePolicy:
    def test_inspect_allowed(self, compose: Path, tmp_path: Path) -> None:
        rules = _inserted_rules(compose, tmp_path)
        assert _allowed(rules, "GET", f"/v1.47/volumes/{_VOLUME}")

    def test_release_allowed(self, compose: Path, tmp_path: Path) -> None:
        """Without DELETE no capture volume is ever released."""
        rules = _inserted_rules(compose, tmp_path)
        assert _allowed(rules, "DELETE", f"/v1.47/volumes/{_VOLUME}")
        assert _allowed(rules, "DELETE", f"/volumes/{_VOLUME}")

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("DELETE", "/v1.47/volumes/syn-env-main_db-data"),
            ("DELETE", "/v1.47/volumes/syn-capture-short"),
            ("DELETE", f"/v1.47/volumes/{_VOLUME}x"),
            ("DELETE", "/v1.47/volumes"),
            ("POST", "/v1.47/volumes/create"),
            ("POST", f"/v1.47/volumes/{_VOLUME}"),
            ("DELETE", "/v1.47/volumes/prune"),
        ],
    )
    def test_stays_narrow(self, compose: Path, tmp_path: Path, method: str, path: str) -> None:
        rules = _inserted_rules(compose, tmp_path)
        assert not _allowed(rules, method, path)
