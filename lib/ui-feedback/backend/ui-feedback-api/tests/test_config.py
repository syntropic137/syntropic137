"""Settings must tolerate the host application's environment.

ui_feedback is mounted inside syn-api and shares its .env, so the environment
always carries keys that are not UI_FEEDBACK_*. pydantic-settings rejects
those as extra inputs unless the model says otherwise, and the failure is
create_app() raising at import time on any machine with a .env.
"""

from pathlib import Path

import pytest

from ui_feedback.config import Settings

pytestmark = pytest.mark.unit


def test_settings_ignore_foreign_env_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_WORKSPACE_POOL_SIZE", "100")
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("UI_FEEDBACK_PORT", "8137")

    settings = Settings(_env_file=None)

    assert settings.port == 8137
    assert not hasattr(settings, "syn_workspace_pool_size")


def test_settings_ignore_foreign_env_file_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SYN_ENVIRONMENT=development\nUI_FEEDBACK_HOST=127.0.0.1\n")

    settings = Settings(_env_file=env_file)

    assert settings.host == "127.0.0.1"
