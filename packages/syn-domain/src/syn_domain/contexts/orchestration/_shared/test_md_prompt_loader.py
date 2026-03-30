"""Tests for the markdown prompt loader (ISS-398)."""

from __future__ import annotations

from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.md_prompt_loader import (
    MdPrompt,
    load_md_prompt,
    normalize_frontmatter,
)


@pytest.mark.unit
class TestLoadMdPrompt:
    """Tests for load_md_prompt()."""

    def test_load_md_with_frontmatter(self, tmp_path: Path) -> None:
        md_file = tmp_path / "phase.md"
        md_file.write_text(
            "---\nmodel: sonnet\nmax-tokens: 4096\n---\n\nYou are a research assistant.\n"
        )
        result = load_md_prompt(md_file)
        assert result.content == "You are a research assistant."
        assert result.metadata == {"model": "sonnet", "max-tokens": 4096}

    def test_load_md_without_frontmatter(self, tmp_path: Path) -> None:
        md_file = tmp_path / "phase.md"
        md_file.write_text("Just a plain prompt.\n\nWith multiple paragraphs.\n")
        result = load_md_prompt(md_file)
        assert result.content == "Just a plain prompt.\n\nWith multiple paragraphs."
        assert result.metadata == {}

    def test_load_md_empty_frontmatter(self, tmp_path: Path) -> None:
        md_file = tmp_path / "phase.md"
        md_file.write_text("---\n---\n\nBody content here.\n")
        result = load_md_prompt(md_file)
        assert result.content == "Body content here."
        assert result.metadata == {}

    def test_load_md_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError, match="Prompt file not found"):
            load_md_prompt(Path("/nonexistent/phase.md"))

    def test_load_md_malformed_frontmatter(self, tmp_path: Path) -> None:
        md_file = tmp_path / "phase.md"
        md_file.write_text("---\n: invalid: yaml: [[\n---\n\nBody.\n")
        with pytest.raises(ValueError, match="Malformed YAML frontmatter"):
            load_md_prompt(md_file)

    def test_load_md_frontmatter_not_mapping(self, tmp_path: Path) -> None:
        md_file = tmp_path / "phase.md"
        md_file.write_text("---\n- just\n- a\n- list\n---\n\nBody.\n")
        with pytest.raises(ValueError, match="must be a mapping"):
            load_md_prompt(md_file)

    def test_body_whitespace_stripping(self, tmp_path: Path) -> None:
        md_file = tmp_path / "phase.md"
        md_file.write_text("---\nmodel: sonnet\n---\n\n\n  Body with indent.\n\n\n")
        result = load_md_prompt(md_file)
        assert result.content == "Body with indent."

    def test_full_claude_code_command_format(self, tmp_path: Path) -> None:
        """Test the full Claude Code command format from the issue."""
        md_file = tmp_path / "discovery.md"
        md_file.write_text(
            "---\n"
            "model: sonnet\n"
            'argument-hint: "<research topic or question>"\n'
            "allowed-tools: Bash, Read, Grep, Glob\n"
            "max-tokens: 4096\n"
            "timeout-seconds: 300\n"
            "---\n"
            "\n"
            "You are a research assistant conducting initial exploration.\n"
            "\n"
            "## Your Task\n"
            "$ARGUMENTS\n"
            "\n"
            "## How to Approach This\n"
            "1. Identify key areas of interest\n"
            "2. Gather relevant context from the codebase\n"
            "3. Define 3-5 research questions\n"
            "\n"
            "Output a structured research scope with your initial questions.\n"
        )
        result = load_md_prompt(md_file)
        assert result.metadata["model"] == "sonnet"
        assert result.metadata["argument-hint"] == "<research topic or question>"
        assert result.metadata["allowed-tools"] == "Bash, Read, Grep, Glob"
        assert result.metadata["max-tokens"] == 4096
        assert result.metadata["timeout-seconds"] == 300
        assert "$ARGUMENTS" in result.content
        assert result.content.startswith("You are a research assistant")

    def test_load_md_no_trailing_newline(self, tmp_path: Path) -> None:
        md_file = tmp_path / "phase.md"
        md_file.write_text("---\nmodel: haiku\n---\nPrompt content")
        result = load_md_prompt(md_file)
        assert result.content == "Prompt content"
        assert result.metadata == {"model": "haiku"}

    def test_md_prompt_is_frozen(self) -> None:
        prompt = MdPrompt(content="test", metadata={})
        with pytest.raises(AttributeError):
            prompt.content = "changed"  # type: ignore[misc]


@pytest.mark.unit
class TestNormalizeFrontmatter:
    """Tests for normalize_frontmatter()."""

    def test_kebab_to_snake_conversion(self) -> None:
        metadata = {
            "argument-hint": "[task]",
            "max-tokens": 4096,
            "timeout-seconds": 300,
        }
        result = normalize_frontmatter(metadata)
        assert result == {
            "argument_hint": "[task]",
            "max_tokens": 4096,
            "timeout_seconds": 300,
        }

    def test_model_passthrough(self) -> None:
        result = normalize_frontmatter({"model": "opus"})
        assert result == {"model": "opus"}

    def test_allowed_tools_comma_string(self) -> None:
        result = normalize_frontmatter({"allowed-tools": "Read, Grep, Bash"})
        assert result == {"allowed_tools": ["Read", "Grep", "Bash"]}

    def test_allowed_tools_yaml_list(self) -> None:
        result = normalize_frontmatter({"allowed-tools": ["Read", "Grep"]})
        assert result == {"allowed_tools": ["Read", "Grep"]}

    def test_allowed_tools_single_item(self) -> None:
        result = normalize_frontmatter({"allowed-tools": "Bash"})
        assert result == {"allowed_tools": ["Bash"]}

    def test_all_supported_keys(self) -> None:
        metadata = {
            "model": "sonnet",
            "argument-hint": "[desc]",
            "allowed-tools": "Read, Write",
            "max-tokens": 8192,
            "timeout-seconds": 600,
        }
        result = normalize_frontmatter(metadata)
        assert result == {
            "model": "sonnet",
            "argument_hint": "[desc]",
            "allowed_tools": ["Read", "Write"],
            "max_tokens": 8192,
            "timeout_seconds": 600,
        }

    def test_empty_metadata(self) -> None:
        assert normalize_frontmatter({}) == {}

    def test_unknown_keys_pass_through(self) -> None:
        result = normalize_frontmatter({"description": "test", "custom-key": "value"})
        assert result == {"description": "test", "custom-key": "value"}
