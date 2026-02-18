#!/usr/bin/env python3
"""Generate llms.txt from API documentation markdown files.

Reads all docs/api/v1/*.md files and concatenates them into a single
structured text file following the llms.txt convention (https://llmstxt.org/).

Usage:
    python scripts/generate_llms_txt.py
    just generate-llms-txt
"""

from __future__ import annotations

from pathlib import Path


def generate_llms_txt() -> str:
    """Generate llms.txt content from API docs."""
    docs_dir = Path("docs/api")
    v1_dir = docs_dir / "v1"

    lines: list[str] = []

    # Header
    lines.append("# AEF API Reference")
    lines.append("")
    lines.append("> Programmatic interface to the Syntropic137")
    lines.append("> Version: 0.1.0")
    lines.append("")

    # Read index for overview
    index_file = docs_dir / "index.md"
    if index_file.exists():
        content = index_file.read_text()
        # Extract just the Quick Start and Architecture sections
        for section in ["## Quick Start", "## Architecture", "## Result Type"]:
            start = content.find(section)
            if start != -1:
                # Find next ## or end of file
                next_section = content.find("\n## ", start + len(section))
                if next_section == -1:
                    next_section = len(content)
                lines.append(content[start:next_section].strip())
                lines.append("")

    # Module docs in logical order
    module_order = [
        "types",
        "auth",
        "workflows",
        "workspaces",
        "sessions",
        "artifacts",
        "github",
        "observability",
    ]

    for module_name in module_order:
        md_file = v1_dir / f"{module_name}.md"
        if md_file.exists():
            content = md_file.read_text().strip()
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    """Generate and write llms.txt."""
    output_path = Path("docs/api/llms.txt")
    content = generate_llms_txt()
    output_path.write_text(content)
    print(f"Generated {output_path} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
