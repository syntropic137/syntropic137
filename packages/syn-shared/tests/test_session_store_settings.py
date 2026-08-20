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

from syn_shared.env_constants import (
    ENV_AGENTIC_SESSION_STORE_AUTH,
    ENV_AGENTIC_SESSION_STORE_DEPLOYMENT,
    ENV_AGENTIC_SESSION_STORE_PARTITION,
    ENV_AGENTIC_SESSION_STORE_PROVIDER,
    ENV_AGENTIC_SESSION_STORE_SPOOL,
    ENV_AGENTIC_SESSION_STORE_TAGS,
    ENV_AGENTIC_SESSION_STORE_URL,
    SESSION_STORE_CONTRACT_ENV_VARS,
)
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


@pytest.mark.unit
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

    def test_the_contract_set_is_exactly_the_declared_constants(self) -> None:
        """Pinned by NAME, not by count.

        The count was 6 and is now 7 (DEPLOYMENT). A bare length assertion
        makes every addition look like a break while catching nothing about
        WHICH variable was added, so it is spelled out instead.
        """
        assert (
            frozenset(
                {
                    ENV_AGENTIC_SESSION_STORE_PROVIDER,
                    ENV_AGENTIC_SESSION_STORE_URL,
                    ENV_AGENTIC_SESSION_STORE_AUTH,
                    ENV_AGENTIC_SESSION_STORE_SPOOL,
                    ENV_AGENTIC_SESSION_STORE_PARTITION,
                    ENV_AGENTIC_SESSION_STORE_TAGS,
                    ENV_AGENTIC_SESSION_STORE_DEPLOYMENT,
                }
            )
            == SESSION_STORE_CONTRACT_ENV_VARS
        )
        assert all(n.startswith("AGENTIC_SESSION_STORE_") for n in SESSION_STORE_CONTRACT_ENV_VARS)


@pytest.mark.unit
class TestUnauthenticatedIsSurfacedNotRefused:
    """A URL with no token is legitimate, and also the common mistake.

    It must stay enabled - refusing would break an open store on a trusted
    network - but it must be detectable, because its failure mode is a 401 at
    finalize with the diagnostic suppressed.
    """

    def test_url_without_token_stays_enabled(self) -> None:
        s = SessionStoreSettings(url="https://store.example.com", auth_token=None)
        assert s.is_enabled
        assert s.is_unauthenticated

    def test_url_with_token_is_not_flagged(self) -> None:
        s = SessionStoreSettings(url="https://store.example.com", auth_token=SecretStr("t"))
        assert s.is_enabled
        assert not s.is_unauthenticated

    def test_disabled_store_is_never_flagged(self) -> None:
        s = SessionStoreSettings(url=None)
        assert not s.is_enabled
        assert not s.is_unauthenticated


@pytest.mark.unit
class TestTheStoreLabel:
    """The label exists so a posture line can name WHICH store, safely.

    The posture line logs no part of SYN_SESSION_STORE_URL, because every part
    of a URL is operator-supplied and could carry a credential. That leaves two
    stores differing only by path indistinguishable, which is what the label
    fixes (#849). Everything here defends the property that makes it loggable:
    it is an operator-declared identifier, not derived from anything secret.
    """

    @pytest.mark.parametrize(
        "raw",
        ["tenant-a", "tenant_a", "tenant.a", "TenantA", "a", "z" * 64, "0"],
    )
    def test_a_plain_identifier_is_kept(self, raw: str) -> None:
        assert SessionStoreSettings(url="https://s", label=raw).display_label == raw

    def test_surrounding_whitespace_is_trimmed(self) -> None:
        s = SessionStoreSettings(url="https://s", label="  tenant-a  ")
        assert s.display_label == "tenant-a"
        assert not s.has_unusable_label

    @pytest.mark.parametrize(
        "raw",
        [
            "tenant a",
            "tenant/a",
            "a\nb",
            "a\tb",
            "\x1b[31mred",
            "tenant\u2013a",  # en dash, not a hyphen
            "tenant\u200db",  # zero-width joiner
            "\u202etnanet",  # right-to-left override
            "z" * 65,
            "https://store.example/tenant-a",
        ],
        ids=[
            "space",
            "slash",
            "newline",
            "tab",
            "ansi-escape",
            "en-dash-homoglyph",
            "zero-width-joiner",
            "bidi-override",
            "one-over-the-limit",
            "a-pasted-url",
        ],
    )
    def test_anything_that_is_not_an_identifier_is_refused(self, raw: str) -> None:
        """Refused, not repaired.

        Sanitising into a shorter or cleaned-up string would mean the logged
        text is not the configured value, which defeats the point of the field.
        """
        s = SessionStoreSettings(url="https://s", label=raw)
        assert s.display_label == ""
        assert s.has_unusable_label

    def test_an_over_long_label_is_refused_rather_than_truncated(self) -> None:
        """An earlier version truncated to 64 and appended "...", making 67.

        Beyond the arithmetic, truncation logs a value the operator never set.
        """
        s = SessionStoreSettings(url="https://s", label="z" * 200)
        assert s.display_label == ""

    def test_unset_is_not_the_same_as_unusable(self) -> None:
        """Both yield "", but only one is a misconfiguration worth reporting."""
        unset = SessionStoreSettings(url="https://s")
        assert unset.display_label == ""
        assert not unset.has_unusable_label

        blank = SessionStoreSettings(url="https://s", label="   ")
        assert blank.display_label == ""
        assert not blank.has_unusable_label

    def test_the_label_is_read_from_the_environment(self) -> None:
        """The whole point is that an operator sets this per deployment."""
        with patch.dict(os.environ, {"SYN_SESSION_STORE_LABEL": "tenant-a"}):
            assert SessionStoreSettings(url="https://s").display_label == "tenant-a"
