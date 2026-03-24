"""Tests for 1Password secret resolution and vault_name_for_env."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from syn_shared.settings.op_resolver import (
    reset_op_resolver,
    resolve_op_secrets,
    vault_name_for_env,
)


@pytest.fixture(autouse=True)
def clear_resolver_cache() -> None:
    reset_op_resolver()
    yield
    reset_op_resolver()


# ---------------------------------------------------------------------------
# vault_name_for_env
# ---------------------------------------------------------------------------


class TestVaultNameForEnv:
    def test_development(self) -> None:
        assert vault_name_for_env("development") == "syn137-dev"

    def test_beta(self) -> None:
        assert vault_name_for_env("beta") == "syn137-beta"

    def test_staging(self) -> None:
        assert vault_name_for_env("staging") == "syn137-staging"

    def test_production(self) -> None:
        assert vault_name_for_env("production") == "syn137-prod"

    def test_unknown_env_raises(self) -> None:
        with pytest.raises(ValueError, match="No vault mapping"):
            vault_name_for_env("custom")

    def test_test_env_raises(self) -> None:
        with pytest.raises(ValueError, match="No vault mapping"):
            vault_name_for_env("test")


# ---------------------------------------------------------------------------
# resolve_op_secrets — APP_ENVIRONMENT-driven resolution
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
    """resolve_op_secrets derives vault from APP_ENVIRONMENT."""

    def _patch_op(self, app_env: str, item_json: str):
        """Context manager: patches op availability and subprocess.run."""
        run_result = MagicMock()
        run_result.returncode = 0
        run_result.stdout = item_json

        return (
            patch(
                "syn_shared.settings.op_resolver.op_available",
                return_value=True,
            ),
            patch(
                "syn_shared.settings.op_client.subprocess.run",
                return_value=run_result,
            ),
            patch.dict(os.environ, {"APP_ENVIRONMENT": app_env}, clear=False),
        )

    def test_development_fetches_from_dev_vault(self) -> None:
        patches = self._patch_op("development", _make_op_item("development"))
        with patches[0], patches[1] as mock_run, patches[2]:
            resolve_op_secrets.__wrapped__()
        # Verify it called op with the correct vault
        call_args = mock_run.call_args[0][0]
        assert "--vault" in call_args
        vault_idx = call_args.index("--vault") + 1
        assert call_args[vault_idx] == "syn137-dev"

    def test_production_fetches_from_prod_vault(self) -> None:
        patches = self._patch_op("production", _make_op_item("production"))
        with patches[0], patches[1] as mock_run, patches[2]:
            resolve_op_secrets.__wrapped__()
        call_args = mock_run.call_args[0][0]
        vault_idx = call_args.index("--vault") + 1
        assert call_args[vault_idx] == "syn137-prod"

    def test_test_env_skips_resolution(self) -> None:
        """APP_ENVIRONMENT=test should skip 1Password entirely."""
        patches = self._patch_op("test", _make_op_item("test"))
        with patches[0], patches[1] as mock_run, patches[2]:
            resolve_op_secrets.__wrapped__()
        mock_run.assert_not_called()

    def test_offline_env_skips_resolution(self) -> None:
        """APP_ENVIRONMENT=offline should skip 1Password entirely."""
        patches = self._patch_op("offline", _make_op_item("offline"))
        with patches[0], patches[1] as mock_run, patches[2]:
            resolve_op_secrets.__wrapped__()
        mock_run.assert_not_called()

    def test_unset_env_skips_resolution(self) -> None:
        """No APP_ENVIRONMENT should skip 1Password entirely."""
        run_result = MagicMock()
        run_result.returncode = 0
        run_result.stdout = "{}"
        env_without = {k: v for k, v in os.environ.items() if k != "APP_ENVIRONMENT"}
        with (
            patch("syn_shared.settings.op_resolver.parse_env_file", return_value={}),
            patch("syn_shared.settings.op_resolver.op_available", return_value=True),
            patch(
                "syn_shared.settings.op_client.subprocess.run", return_value=run_result
            ) as mock_run,
            patch.dict(os.environ, env_without, clear=True),
        ):
            resolve_op_secrets.__wrapped__()
        mock_run.assert_not_called()

    def test_injects_secrets_into_environ(self) -> None:
        """Verify fields from the item are injected into os.environ."""
        patches = self._patch_op("development", _make_op_item("development"))
        env_without = {k: v for k, v in os.environ.items() if k not in ("SYN_GITHUB_APP_ID",)}
        env_without["APP_ENVIRONMENT"] = "development"
        with (
            patches[0],
            patches[1],
            patch.dict(os.environ, env_without, clear=True),
        ):
            resolve_op_secrets.__wrapped__()
            assert os.environ.get("SYN_GITHUB_APP_ID") == "12345"
