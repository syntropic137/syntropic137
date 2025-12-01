#!/usr/bin/env python3
"""Generate .env.example from Settings class definitions.

This script introspects the Settings class and generates a well-documented
.env.example file with all environment variables, their defaults, and descriptions.

Usage:
    python scripts/generate_env_example.py
    # or
    just gen-env

The generated file will be placed at the project root as .env.example
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args, get_origin

from pydantic import SecretStr

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

# Add packages to path for import
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "aef-shared" / "src"))

from aef_shared.settings.config import Settings  # noqa: E402


def get_env_var_name(field_name: str) -> str:
    """Convert field name to environment variable name."""
    return field_name.upper()


def get_default_value(field_info: FieldInfo) -> str:
    """Get the default value as a string for .env file."""
    default = field_info.default

    if default is None:
        return ""

    # Handle enums
    if hasattr(default, "value"):
        return str(default.value)

    # Handle booleans
    if isinstance(default, bool):
        return str(default).lower()

    return str(default)


def is_secret_type(field_type: type[Any]) -> bool:
    """Check if field type is a secret (should not show default)."""
    # Check direct type
    if field_type is SecretStr:
        return True

    # Check Optional[SecretStr]
    origin = get_origin(field_type)
    if origin is not None:
        args = get_args(field_type)
        if SecretStr in args:
            return True

    return False


def is_required(field_info: FieldInfo) -> bool:
    """Check if field is required (no default)."""
    return field_info.default is ... or (field_info.default is None and field_info.is_required())


def format_description(description: str | None, max_width: int = 78) -> list[str]:
    """Format description as comment lines."""
    if not description:
        return []

    # Wrap text to max width (accounting for "# " prefix)
    wrapped = textwrap.wrap(description, width=max_width - 2)
    return [f"# {line}" for line in wrapped]


def get_section_from_field_name(field_name: str) -> str:
    """Infer section from field name prefix."""
    prefixes = {
        "app_": "APPLICATION",
        "database_": "DATABASE",
        "event_store_": "EVENT STORE",
        "log_": "LOGGING",
        "anthropic_": "AGENT CONFIGURATION",
        "openai_": "AGENT CONFIGURATION",
        "default_agent_": "AGENT CONFIGURATION",
        "default_max_": "AGENT CONFIGURATION",
        "artifact_": "STORAGE",
        "s3_": "STORAGE",
    }

    for prefix, section in prefixes.items():
        if field_name.startswith(prefix):
            return section

    return "OTHER"


def generate_env_example() -> str:
    """Generate .env.example content from Settings class."""
    lines: list[str] = []

    # Header
    lines.extend(
        [
            "# " + "=" * 76,
            "# AGENTIC ENGINEERING FRAMEWORK - ENVIRONMENT CONFIGURATION",
            "# " + "=" * 76,
            "#",
            "# This file is AUTO-GENERATED from the Settings class.",
            "# Do not edit manually - run: just gen-env",
            "#",
            "# Copy this file to .env and fill in your values.",
            "# Required variables are marked with [REQUIRED].",
            "# " + "=" * 76,
            "",
        ]
    )

    # Group fields by section
    sections: dict[str, list[tuple[str, FieldInfo, type[Any]]]] = {}

    for field_name, field_info in Settings.model_fields.items():
        # Get field type from annotations
        field_type = Settings.__annotations__.get(field_name, str)

        section = get_section_from_field_name(field_name)
        if section not in sections:
            sections[section] = []
        sections[section].append((field_name, field_info, field_type))

    # Define section order
    section_order = [
        "APPLICATION",
        "DATABASE",
        "EVENT STORE",
        "LOGGING",
        "AGENT CONFIGURATION",
        "STORAGE",
        "OTHER",
    ]

    # Generate each section
    for section in section_order:
        if section not in sections:
            continue

        fields = sections[section]

        # Section header
        lines.extend(
            [
                "# " + "=" * 76,
                f"# {section}",
                "# " + "=" * 76,
                "",
            ]
        )

        for field_name, field_info, field_type in fields:
            env_name = get_env_var_name(field_name)
            default = get_default_value(field_info)
            description = field_info.description

            # Add required marker to description
            required_marker = ""
            if is_required(field_info):
                required_marker = "[REQUIRED] "
            elif is_secret_type(field_type) and default == "":
                # Secrets without defaults are typically required when used
                required_marker = "[REQUIRED when using this feature] "

            # Format description
            if description:
                full_description = required_marker + description
                desc_lines = format_description(full_description)
                lines.extend(desc_lines)

            # Add the variable
            if is_secret_type(field_type):
                # Don't show secret values, even defaults
                lines.append(f"{env_name}=")
            else:
                lines.append(f"{env_name}={default}")

            lines.append("")

    return "\n".join(lines)


def main() -> None:
    """Generate .env.example file."""
    content = generate_env_example()

    output_path = PROJECT_ROOT / ".env.example"

    # Write to file
    output_path.write_text(content)

    print(f"✅ Generated {output_path}")
    print(f"   {len(Settings.model_fields)} environment variables documented")


if __name__ == "__main__":
    main()
