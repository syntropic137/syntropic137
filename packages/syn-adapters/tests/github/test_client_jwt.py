"""Tests for decode_private_key() format dispatch."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from syn_adapters.github.client_jwt import decode_private_key

# Minimal valid PEM for testing format detection (not a real key)
TEST_PEM = "-----BEGIN PRIVATE KEY-----\nMIIBVAIBADANBgkqhki\n-----END PRIVATE KEY-----\n"


class TestDecodeBase64:
    def test_base64_key(self) -> None:
        encoded = base64.b64encode(TEST_PEM.encode()).decode()
        result = decode_private_key(encoded)
        assert result == TEST_PEM

    def test_invalid_base64(self) -> None:
        with pytest.raises(ValueError, match="Failed to decode"):
            decode_private_key("not-valid-base64!!!")


class TestDecodeRawPem:
    def test_raw_pem_passthrough(self) -> None:
        result = decode_private_key(TEST_PEM)
        assert result == TEST_PEM.strip()

    def test_raw_pem_with_whitespace(self) -> None:
        result = decode_private_key(f"  {TEST_PEM}  ")
        assert result == TEST_PEM.strip()


class TestDecodeFileReference:
    def test_file_reference_absolute(self, tmp_path: Path) -> None:
        key_file = tmp_path / "test-key.pem"
        key_file.write_text(TEST_PEM)
        result = decode_private_key(f"file:{key_file}")
        assert result == TEST_PEM

    def test_file_reference_relative(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key_file = tmp_path / "secrets" / "key.pem"
        key_file.parent.mkdir()
        key_file.write_text(TEST_PEM)
        monkeypatch.chdir(tmp_path)
        result = decode_private_key("file:secrets/key.pem")
        assert result == TEST_PEM

    def test_file_reference_with_whitespace(self, tmp_path: Path) -> None:
        key_file = tmp_path / "key.pem"
        key_file.write_text(TEST_PEM)
        result = decode_private_key(f"  file: {key_file} ")
        assert result == TEST_PEM

    def test_file_not_found(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            decode_private_key("file:/nonexistent/key.pem")

    def test_file_is_directory(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a file"):
            decode_private_key(f"file:{tmp_path}")

    def test_file_missing_pem_header(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.pem"
        bad_file.write_text("this is not a valid file")
        with pytest.raises(ValueError, match="does not contain a valid PEM header"):
            decode_private_key(f"file:{bad_file}")
