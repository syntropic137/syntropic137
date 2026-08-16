"""Tests for SessionStoreSettings and the session-store env-name centralization.

Two things are guarded here:

1. The settings object defaults to DISABLED. Syntropic137 must stay deployable
   as a full self-hosted stack by operators who have no SeshMagic instance.
2. Session-store env var names appear as string literals in exactly one place
   (``syn_shared.env_constants``), per the project rule against scattered env
   name literals.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from syn_shared.env_constants import SESSION_STORE_CONTRACT_ENV_VARS
from syn_shared.settings.config import Settings
from syn_shared.settings.session_store import (
    DEFAULT_SPOOL_DIR,
    SESHMAGIC_PROVIDER,
    SessionStoreSettings,
)

# The repo root is three parents up from packages/syn-shared/tests/<file>.
_REPO_ROOT = Path(__file__).resolve().parents[3]

_SEARCH_ROOTS = (
    _REPO_ROOT / "packages" / "syn-domain" / "src",
    _REPO_ROOT / "packages" / "syn-shared" / "src",
    _REPO_ROOT / "packages" / "syn-adapters" / "src",
    _REPO_ROOT / "apps" / "syn-api" / "src",
)

#: The only file allowed to spell these names out.
_DEFINING_FILE = _REPO_ROOT / "packages" / "syn-shared" / "src" / "syn_shared" / "env_constants.py"


class TestDefaultsOff:
    """Opt-in: no configuration means no session capture."""

    def test_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = SessionStoreSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.url is None
        assert settings.auth_token is None
        assert settings.is_enabled is False

    def test_enabled_only_by_url(self) -> None:
        with patch.dict(os.environ, {"SYN_SESSION_STORE_URL": "https://s.example"}, clear=True):
            settings = SessionStoreSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.is_enabled is True
        assert settings.url == "https://s.example"

    def test_settings_exposes_session_store_property(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            assert settings.session_store.is_enabled is False

    def test_provider_and_spool_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = SessionStoreSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.provider == SESHMAGIC_PROVIDER == "seshmagic"
        assert settings.spool_dir == DEFAULT_SPOOL_DIR == "/spool"

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_overrides_fall_back_to_defaults(self, blank: str) -> None:
        env = {
            "SYN_SESSION_STORE_PROVIDER": blank,
            "SYN_SESSION_STORE_SPOOL_DIR": blank,
        }
        with patch.dict(os.environ, env, clear=True):
            settings = SessionStoreSettings(_env_file=None)  # type: ignore[call-arg]
        assert settings.provider == SESHMAGIC_PROVIDER
        assert settings.spool_dir == DEFAULT_SPOOL_DIR


class TestTokenIsACredential:
    """The write token must not leak through repr, str, or model dumps."""

    def test_auth_value_is_the_only_way_out(self) -> None:
        token = "tok-do-not-log"  # test fixture, not a real credential
        settings = SessionStoreSettings(  # type: ignore[call-arg]
            _env_file=None, url="https://s.example", auth_token=SecretStr(token)
        )
        assert settings.auth_value == token
        assert token not in repr(settings)
        assert token not in str(settings.model_dump())

    def test_auth_value_empty_when_unset(self) -> None:
        settings = SessionStoreSettings(_env_file=None, url="https://s.example")  # type: ignore[call-arg]
        assert settings.auth_value == ""


class TestNoScatteredEnvNameLiterals:
    """Poka-yoke: session-store env var names live in env_constants only.

    Standing project rule — an env var name written inline is how two call sites
    end up reading different variables. This walks the AST so comments and
    docstrings mentioning a variable stay legal; only executable string values
    are rejected.
    """

    @staticmethod
    def _docstring_constants(tree: ast.Module) -> set[int]:
        skip: set[int] = set()
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant):
                    skip.add(id(child.value))
        return skip

    def test_no_bare_session_store_env_literals(self) -> None:
        offenders: list[str] = []

        for root in _SEARCH_ROOTS:
            if not root.exists():
                continue
            for path in root.rglob("*.py"):
                if path == _DEFINING_FILE:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))
                skip = self._docstring_constants(tree)
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and id(node) not in skip
                        and node.value in SESSION_STORE_CONTRACT_ENV_VARS
                    ):
                        offenders.append(
                            f"{path.relative_to(_REPO_ROOT)}:{node.lineno} {node.value}"
                        )

        assert not offenders, (
            "Session-store env var names must come from syn_shared.env_constants, "
            "not bare literals:\n  " + "\n  ".join(offenders)
        )

    def test_contract_set_matches_the_six_constants(self) -> None:
        assert len(SESSION_STORE_CONTRACT_ENV_VARS) == 6
        assert all(n.startswith("AGENTIC_SESSION_STORE_") for n in SESSION_STORE_CONTRACT_ENV_VARS)
