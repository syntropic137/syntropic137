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
from aef_shared.settings.github import GitHubAppSettings  # noqa: E402
from aef_shared.settings.workspace import (  # noqa: E402
    ContainerLoggingSettings,
    GitIdentitySettings,
    WorkspaceSecuritySettings,
    WorkspaceSettings,
)


def get_env_var_name(field_name: str, prefix: str = "") -> str:
    """Convert field name to environment variable name."""
    if prefix:
        return f"{prefix}{field_name.upper()}"
    return field_name.upper()


def get_default_value(field_info: FieldInfo) -> str:
    """Get the default value as a string for .env file."""
    from pydantic_core import PydanticUndefined

    default = field_info.default

    if default is None or default is PydanticUndefined:
        return ""

    # Handle enums
    if hasattr(default, "value"):
        return str(default.value)

    # Handle booleans
    if isinstance(default, bool):
        return str(default).lower()

    # Handle lists/tuples (e.g., regex patterns)
    if isinstance(default, list | tuple):
        return ""  # Empty for complex defaults

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


def generate_settings_section(
    settings_class: type,
    section_name: str,
    prefix: str = "",
    description: str | None = None,
) -> list[str]:
    """Generate env vars for a settings class."""
    lines: list[str] = []

    # Section header
    lines.extend(
        [
            "# " + "=" * 76,
            f"# {section_name}",
            "# " + "=" * 76,
        ]
    )

    if description:
        lines.append(f"# {description}")

    lines.append("")

    for field_name, field_info in settings_class.model_fields.items():
        # Get field type from annotations
        field_type = settings_class.__annotations__.get(field_name, str)

        env_name = get_env_var_name(field_name, prefix)
        default = get_default_value(field_info)
        field_description = field_info.description

        # Add required marker to description
        required_marker = ""
        if is_required(field_info):
            required_marker = "[REQUIRED] "
        elif is_secret_type(field_type) and default == "":
            required_marker = "[REQUIRED when using this feature] "

        # Format description
        if field_description:
            full_description = required_marker + field_description
            desc_lines = format_description(full_description)
            lines.extend(desc_lines)

        # Add the variable
        if is_secret_type(field_type):
            lines.append(f"{env_name}=")
        else:
            lines.append(f"{env_name}={default}")

        lines.append("")

    return lines


def generate_env_example() -> str:
    """Generate .env.example content from all Settings classes."""
    lines: list[str] = []

    # Header
    lines.extend(
        [
            "# " + "=" * 76,
            "# AGENTIC ENGINEERING FRAMEWORK - ENVIRONMENT CONFIGURATION",
            "# " + "=" * 76,
            "#",
            "# This file is AUTO-GENERATED from the Settings classes.",
            "# Do not edit manually - run: just gen-env",
            "#",
            "# Copy this file to .env and fill in your values.",
            "# Required variables are marked with [REQUIRED].",
            "# " + "=" * 76,
            "",
        ]
    )

    # Group main Settings fields by section
    sections: dict[str, list[tuple[str, FieldInfo, type[Any]]]] = {}

    for field_name, field_info in Settings.model_fields.items():
        field_type = Settings.__annotations__.get(field_name, str)
        section = get_section_from_field_name(field_name)
        if section not in sections:
            sections[section] = []
        sections[section].append((field_name, field_info, field_type))

    # Define section order for main Settings
    section_order = [
        "APPLICATION",
        "DATABASE",
        "EVENT STORE",
        "LOGGING",
        "AGENT CONFIGURATION",
        "STORAGE",
        "OTHER",
    ]

    # Generate main Settings sections
    for section in section_order:
        if section not in sections:
            continue

        fields = sections[section]

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

            required_marker = ""
            if is_required(field_info):
                required_marker = "[REQUIRED] "
            elif is_secret_type(field_type) and default == "":
                required_marker = "[REQUIRED when using this feature] "

            if description:
                full_description = required_marker + description
                desc_lines = format_description(full_description)
                lines.extend(desc_lines)

            if is_secret_type(field_type):
                lines.append(f"{env_name}=")
            else:
                lines.append(f"{env_name}={default}")

            lines.append("")

    # Add GitHub App Settings (AEF_GITHUB_* prefix)
    lines.extend(
        generate_settings_section(
            GitHubAppSettings,
            "GITHUB APP (Secure Authentication)",
            prefix="AEF_GITHUB_",
            description="GitHub App for secure API access. See docs/deployment/github-app-setup.md",
        )
    )

    # Add Workspace Settings (AEF_WORKSPACE_* prefix)
    lines.extend(
        generate_settings_section(
            WorkspaceSettings,
            "WORKSPACE ISOLATION (ADR-021)",
            prefix="AEF_WORKSPACE_",
            description="All workspaces are isolated by default. These settings control HOW.",
        )
    )

    # Add Workspace Security Settings (AEF_SECURITY_* prefix)
    lines.extend(
        generate_settings_section(
            WorkspaceSecuritySettings,
            "WORKSPACE SECURITY POLICIES",
            prefix="AEF_SECURITY_",
            description="Defaults are maximally restrictive for compromised agent protection.",
        )
    )

    # Add Git Identity Settings (AEF_GIT_* prefix)
    lines.extend(
        generate_settings_section(
            GitIdentitySettings,
            "GIT IDENTITY FOR WORKSPACE COMMITS",
            prefix="AEF_GIT_",
            description="Git identity for agent commits. Prefer GitHub App for authentication.",
        )
    )

    # Add Container Logging Settings (AEF_LOGGING_* prefix)
    lines.extend(
        generate_settings_section(
            ContainerLoggingSettings,
            "CONTAINER LOGGING (ADR-021)",
            prefix="AEF_LOGGING_",
            description="Controls logging inside isolated containers for observability.",
        )
    )

    return "\n".join(lines)


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse an existing .env file into a dict of key=value pairs.

    Preserves values exactly as written (including quoted multi-line values).
    """
    if not path.exists():
        return {}

    env_vars: dict[str, str] = {}
    content = path.read_text()

    current_key: str | None = None
    current_value_lines: list[str] = []
    in_multiline = False

    for line in content.split("\n"):
        # Skip comments and empty lines (unless in multiline)
        if not in_multiline:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

        if in_multiline:
            current_value_lines.append(line)
            # Check if this line ends the multiline value
            if line.rstrip().endswith('"') and not line.rstrip().endswith('\\"'):
                # End of multiline value
                full_value = "\n".join(current_value_lines)
                if current_key:
                    env_vars[current_key] = full_value
                current_key = None
                current_value_lines = []
                in_multiline = False
            continue

        # Parse KEY=VALUE
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # Check if this starts a multiline value (starts with " but doesn't end with ")
            if value.startswith('"') and not value.endswith('"'):
                in_multiline = True
                current_key = key
                current_value_lines = [value]
            else:
                env_vars[key] = value

    return env_vars


def sync_env_file(example_path: Path, env_path: Path) -> tuple[int, int, int, list[str]]:
    """Sync .env with .env.example idempotently.

    - Preserves existing values in .env
    - Adds new variables from .env.example with default values
    - Preserves extra variables not in .env.example (with warning)
    - Never overwrites user-configured values
    - Returns (existing_count, new_count, total_count, extra_vars)
    """
    # Parse existing .env
    existing_vars = parse_env_file(env_path)

    # Parse .env.example to get structure and defaults
    example_content = example_path.read_text()

    # Track what we're adding and what's in the template
    new_vars: list[str] = []
    template_keys: set[str] = set()

    output_lines: list[str] = []

    for line in example_content.split("\n"):
        stripped = line.strip()

        # Keep comments and section headers as-is
        if not stripped or stripped.startswith("#"):
            output_lines.append(line)
            continue

        # Parse KEY=VALUE
        if "=" in line:
            key, _, default_value = line.partition("=")
            key = key.strip()
            default_value = default_value.strip()
            template_keys.add(key)

            if key in existing_vars:
                # Preserve existing value
                output_lines.append(f"{key}={existing_vars[key]}")
            else:
                # Add new variable with default (empty for secrets)
                output_lines.append(f"{key}={default_value}")
                new_vars.append(key)
        else:
            output_lines.append(line)

    # Find extra variables in .env that aren't in the template
    extra_vars = [key for key in existing_vars if key not in template_keys]

    # Append extra variables in a separate section
    if extra_vars:
        output_lines.extend(
            [
                "",
                "# " + "=" * 76,
                "# EXTERNAL / UNKNOWN VARIABLES",
                "# " + "=" * 76,
                "# These variables are not defined in the AEF settings classes.",
                "# They may come from external tools, plugins, or manual additions.",
                "# Review periodically - remove if no longer needed.",
                "",
            ]
        )
        for key in sorted(extra_vars):
            output_lines.append(f"{key}={existing_vars[key]}")
        output_lines.append("")

    # Write the synced .env
    env_path.write_text("\n".join(output_lines))

    existing_count = len([k for k in existing_vars if k in template_keys])
    new_count = len(new_vars)
    total_count = len(template_keys)

    return existing_count, new_count, total_count, extra_vars


def main() -> None:
    """Generate .env.example and sync .env idempotently."""
    content = generate_env_example()

    example_path = PROJECT_ROOT / ".env.example"
    env_path = PROJECT_ROOT / ".env"

    # Write .env.example
    example_path.write_text(content)
    print(f"✅ Generated {example_path}")

    # Count total env vars (rough count from lines with = that aren't comments)
    total_vars = sum(
        1 for line in content.split("\n") if "=" in line and not line.strip().startswith("#")
    )
    print(f"   {total_vars} environment variables documented")

    # Sync .env idempotently
    if env_path.exists():
        existing, new, total, extra = sync_env_file(example_path, env_path)
        if new > 0:
            print(f"✅ Synced {env_path}")
            print(f"   {existing} existing values preserved")
            print(f"   {new} new variables added")
        else:
            print(f"✅ {env_path} is up to date ({existing} variables)")

        # Warn about external/unknown variables
        if extra:
            print(f"⚠️  {len(extra)} external variables found (not in AEF settings):")
            for var in sorted(extra):
                print(f"   - {var}")
            print("   These are preserved in 'EXTERNAL / UNKNOWN VARIABLES' section.")
    else:
        # Create .env from .env.example
        env_path.write_text(content)
        print(f"✅ Created {env_path} from template")
        print("   ⚠️  Fill in secret values (API keys, private keys, etc.)")


if __name__ == "__main__":
    main()
