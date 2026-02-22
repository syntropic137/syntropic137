"""Tests for 1Password secret resolution and environment mismatch guard."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from syn_shared.settings.op_resolver import (
    _validate_environment_match,
    reset_op_resolver,
    resolve_op_secrets,
)


@pytest.fixture(autouse=True)
def clear_resolver_cache() -> None:
    reset_op_resolver()
    yield
    reset_op_resolver()


# ---------------------------------------------------------------------------
# _validate_environment_match
# ---------------------------------------------------------------------------


class TestValidateEnvironmentMatch:
    def test_matching_dev_passes(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}):
            _validate_environment_match("syn137-dev")  # no raise

    def test_matching_beta_passes(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "beta"}):
            _validate_environment_match("syn137-beta")  # no raise

    def test_matching_staging_passes(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "staging"}):
            _validate_environment_match("syn137-staging")  # no raise

    def test_matching_prod_passes(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "production"}):
            _validate_environment_match("syn137-prod")  # no raise

    def test_mismatch_dev_vault_staging_env_raises(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "staging"}):
            with pytest.raises(EnvironmentError, match="syn137-dev"):
                _validate_environment_match("syn137-dev")

    def test_mismatch_prod_vault_dev_env_raises(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}):
            with pytest.raises(EnvironmentError, match="syn137-prod"):
                _validate_environment_match("syn137-prod")

    def test_test_env_bypasses_check(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
            _validate_environment_match("syn137-prod")  # no raise

    def test_offline_env_bypasses_check(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "offline"}):
            _validate_environment_match("syn137-prod")  # no raise

    def test_missing_app_environment_skips_check(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "APP_ENVIRONMENT"}
        with patch.dict(os.environ, env, clear=True):
            _validate_environment_match("syn137-prod")  # no raise

    def test_unknown_vault_skips_check(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "development"}):
            _validate_environment_match("my-custom-vault")  # no raise

    def test_error_message_is_actionable(self) -> None:
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "staging"}):
            with pytest.raises(EnvironmentError) as exc_info:
                _validate_environment_match("syn137-prod")
        msg = str(exc_info.value)
        assert "syn137-prod" in msg
        assert "production" in msg
        assert "staging" in msg
        assert "Fix:" in msg


# ---------------------------------------------------------------------------
# resolve_op_secrets — environment mismatch triggers error
# ---------------------------------------------------------------------------


def _make_op_item(app_environment: str) -> str:
    return json.dumps(
        {
            "fields": [
                {"label": "APP_ENVIRONMENT", "value": app_environment},
                {"label": "SYN_GITHUB_APP_ID", "value": "12345"},
            ]
        }
    )


class TestResolveOpSecretsEnvGuard:
    """resolve_op_secrets should raise when APP_ENVIRONMENT from 1Password
    contradicts the OP_VAULT-derived expectation."""

    def _patch_op(self, vault: str, item_json: str):
        """Context manager: patches op availability and subprocess.run."""
        run_result = MagicMock()
        run_result.returncode = 0
        run_result.stdout = item_json

        return (
            patch(
                "syn_shared.settings.op_resolver._op_available",
                return_value=True,
            ),
            patch(
                "syn_shared.settings.op_resolver.subprocess.run",
                return_value=run_result,
            ),
            patch.dict(os.environ, {"OP_VAULT": vault}, clear=False),
        )

    def test_matching_env_in_item_passes(self) -> None:
        patches = self._patch_op("syn137-dev", _make_op_item("development"))
        with patches[0], patches[1], patches[2]:
            # Should not raise
            resolve_op_secrets.__wrapped__()

    def test_mismatched_env_in_item_raises(self) -> None:
        """Item says 'production' but vault is syn137-dev → fail fast.

        APP_ENVIRONMENT must be absent from the shell so the item's value
        gets injected (shell always wins over 1Password).
        """
        patches = self._patch_op("syn137-dev", _make_op_item("production"))
        # Clear APP_ENVIRONMENT so the item's 'production' value is injected
        env_without_app_env = {k: v for k, v in os.environ.items() if k != "APP_ENVIRONMENT"}
        with patches[0], patches[1]:
            with patch.dict(os.environ, {**env_without_app_env, "OP_VAULT": "syn137-dev"}, clear=True):
                with pytest.raises(EnvironmentError, match="syn137-dev"):
                    resolve_op_secrets.__wrapped__()

    def test_shell_env_wins_and_mismatch_is_caught(self) -> None:
        """Shell has APP_ENVIRONMENT=production, vault is syn137-dev → fail."""
        patches = self._patch_op("syn137-dev", _make_op_item("development"))
        # Shell sets a conflicting value; since shell wins it won't be overwritten
        # but the resolver still validates after injection
        with patches[0], patches[1]:
            with patch.dict(
                os.environ,
                {"OP_VAULT": "syn137-dev", "APP_ENVIRONMENT": "production"},
                clear=False,
            ):
                with pytest.raises(EnvironmentError, match="syn137-dev"):
                    resolve_op_secrets.__wrapped__()
