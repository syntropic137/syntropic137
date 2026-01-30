#!/usr/bin/env python3
"""Generate auto-generated architecture documentation.

This script regenerates all auto-generatable architecture diagrams:
- Projection subscriptions (from manifest event_to_projections)
- Event flow summary (from manifest relationships)
- Component counts in README (from manifest)

Run after updating the VSA manifest to keep docs in sync.

Usage:
    python scripts/generate-architecture-docs.py
    # or via justfile:
    just docs-gen
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def load_manifest() -> dict[str, Any]:
    """Load the VSA manifest."""
    manifest_path = Path(".topology/aef-manifest.json")
    if not manifest_path.exists():
        print(f"❌ Error: Manifest not found at {manifest_path}")
        print(
            "   Run: vsa manifest --config vsa.yaml --output .topology/aef-manifest.json --include-domain"
        )
        sys.exit(1)

    return json.loads(manifest_path.read_text())


def generate_projection_subscriptions(manifest: dict[str, Any]) -> str:
    """Generate projection subscriptions diagram."""
    domain = manifest.get("domain", {})
    event_to_projections = domain.get("relationships", {}).get("event_to_projections", {})

    # Get top N events by projection count
    event_counts = {event: len(projs) for event, projs in event_to_projections.items()}
    top_events = sorted(event_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Get unique projections
    unique_projections = set()
    for projs in event_to_projections.values():
        unique_projections.update(projs)

    # Build Mermaid graph
    mermaid_lines = ["graph LR"]
    mermaid_lines.append('    subgraph events["Key Events"]')

    # Add top events
    for i, (event, _) in enumerate(top_events, 1):
        mermaid_lines.append(f"        e{i}[{event}]")

    mermaid_lines.append("    end")
    mermaid_lines.append("")
    mermaid_lines.append('    subgraph projections["Projections"]')

    # Add unique projections
    for i, proj in enumerate(sorted(unique_projections)[:15], 1):
        mermaid_lines.append(f"        p{i}[{proj}]")

    mermaid_lines.append("    end")
    mermaid_lines.append("")

    # Add connections
    event_to_id = {event: f"e{i}" for i, (event, _) in enumerate(top_events, 1)}
    proj_to_id = {proj: f"p{i}" for i, proj in enumerate(sorted(unique_projections)[:15], 1)}

    for event, projs in event_to_projections.items():
        if event in event_to_id:
            for proj in projs:
                if proj in proj_to_id:
                    mermaid_lines.append(f"    {event_to_id[event]} --> {proj_to_id[proj]}")

    mermaid_diagram = "\n".join(mermaid_lines)

    # Build full markdown
    content = f"""# Projection Subscriptions

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

**Last Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Data Source:** `.topology/aef-manifest.json`

---

## Overview

This diagram shows which events feed which projections in the AEF system.

**Total Relationships:** {len(event_to_projections)} events → {len(unique_projections)} projections

```mermaid
{mermaid_diagram}
```

---

## Statistics

- **Events with projections:** {len(event_to_projections)}
- **Unique projections:** {len(unique_projections)}
- **Total event-to-projection mappings:** {sum(len(projs) for projs in event_to_projections.values())}

---

## Top Events by Projection Count

| Event | Projections | Count |
|-------|-------------|-------|
"""

    # Add top events table
    for event, count in top_events[:10]:
        projs = event_to_projections[event]
        proj_display = ", ".join(projs[:3])
        if len(projs) > 3:
            proj_display += "..."
        content += f"| {event} | {proj_display} | {count} |\n"

    content += """
---

## Related Documentation

- [Event Architecture](./event-architecture.md) - Domain vs Observability events
- [Infrastructure Data Flow](./infrastructure-data-flow.md)

---

🤖 **This file is auto-generated** - Do not edit manually. To regenerate:

```bash
just docs-gen
```

Or regenerate the manifest first:

```bash
vsa manifest --config vsa.yaml --output .topology/aef-manifest.json --include-domain
just docs-gen
```
"""

    return content


def generate_event_flow_summary(manifest: dict[str, Any]) -> str:
    """Generate event flow summary table."""
    domain = manifest.get("domain", {})
    commands = domain.get("commands", [])
    event_to_projections = domain.get("relationships", {}).get("event_to_projections", {})

    # Build flow summary (top 15 by projection count)
    flows = []
    for event, projections in sorted(
        event_to_projections.items(), key=lambda x: len(x[1]), reverse=True
    )[:15]:
        # Try to find which command creates this event (heuristic: event name starts with command)
        likely_command = "?"
        for cmd in commands:
            cmd_name = cmd if isinstance(cmd, str) else cmd.get("name", "")
            if event.startswith(cmd_name.replace("Command", "")):
                likely_command = cmd_name
                break

        flows.append(
            {
                "command": likely_command,
                "event": event,
                "projections": projections,
                "count": len(projections),
            }
        )

    # Generate markdown
    content = f"""# Event Flow Summary

🤖 **Auto-generated from VSA manifest** - Run `just docs-gen` to update

**Last Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## Top Event Flows

This table shows the most important event flows in AEF (events that feed the most projections):

| Command | Event | Projections | Count |
|---------|-------|-------------|-------|
"""

    for flow in flows:
        proj_display = ", ".join(flow["projections"][:3])
        if flow["count"] > 3:
            proj_display += "..."
        content += f"| {flow['command']} | {flow['event']} | {proj_display} | {flow['count']} |\n"

    content += """
---

## Detailed Flow Diagrams

📝 **Manual diagrams** - These show detailed sequence flows for key operations:

- [Workflow Creation](./workflow-creation.md) - `CreateWorkflow` → `WorkflowCreated` flow

---

## Related Documentation

- [Event Architecture](../event-architecture.md)
- [Projection Subscriptions](../projection-subscriptions.md)

---

🤖 **This file is auto-generated** - Do not edit manually. To regenerate:

```bash
just docs-gen
```
"""

    return content


def update_readme_counts(manifest: dict[str, Any]) -> bool:
    """Update CQRS component counts in README.md."""
    domain = manifest.get("domain", {})
    commands_count = len(domain.get("commands", []))
    events_count = len(domain.get("events", []))
    projections_count = len(domain.get("projections", []))

    readme_path = Path("README.md")
    if not readme_path.exists():
        print("⚠️  README.md not found, skipping count update")
        return False

    readme_content = readme_path.read_text()

    # Update CQRS pattern row in architecture table
    pattern = r"\| CQRS \| Commands \(\d+\) → Events \(\d+\) → Projections \(\d+\) \|"
    replacement = f"| CQRS | Commands ({commands_count}) → Events ({events_count}) → Projections ({projections_count}) |"

    updated_content = re.sub(pattern, replacement, readme_content)

    if updated_content != readme_content:
        readme_path.write_text(updated_content)
        print(
            f"✅ Updated README.md with current counts: {commands_count}/{events_count}/{projections_count}"
        )
        return True
    else:
        print("INFO: README.md already up-to-date")
        return False


def validate_manual_docs() -> list[str]:
    """Check for expected manual documentation files."""
    expected_manual_docs = [
        "docs/architecture/event-architecture.md",
        "docs/architecture/realtime-communication.md",
        "docs/architecture/docker-workspace-lifecycle.md",
        "docs/architecture/infrastructure-data-flow.md",
        "docs/architecture/event-flows/workflow-creation.md",
    ]

    missing = []
    for doc_path in expected_manual_docs:
        if not Path(doc_path).exists():
            missing.append(doc_path)

    return missing


def main() -> None:
    """Main execution."""
    print("🤖 Generating Architecture Documentation...")
    print()

    # Load manifest
    print("📖 Reading VSA manifest...")
    manifest = load_manifest()

    domain = manifest.get("domain", {})
    commands_count = len(domain.get("commands", []))
    events_count = len(domain.get("events", []))
    projections_count = len(domain.get("projections", []))

    print(f"   Commands: {commands_count}")
    print(f"   Events: {events_count}")
    print(f"   Projections: {projections_count}")
    print()

    # Generate auto-generated docs
    files_generated = []

    # 1. Projection subscriptions
    print("📊 Generating projection subscriptions diagram...")
    proj_sub_content = generate_projection_subscriptions(manifest)
    proj_sub_path = Path("docs/architecture/projection-subscriptions.md")
    proj_sub_path.parent.mkdir(parents=True, exist_ok=True)
    proj_sub_path.write_text(proj_sub_content)
    files_generated.append(str(proj_sub_path))
    print(f"   ✅ {proj_sub_path}")

    # 2. Event flow summary
    print("📊 Generating event flow summary...")
    event_flow_content = generate_event_flow_summary(manifest)
    event_flow_path = Path("docs/architecture/event-flows/README.md")
    event_flow_path.parent.mkdir(parents=True, exist_ok=True)
    event_flow_path.write_text(event_flow_content)
    files_generated.append(str(event_flow_path))
    print(f"   ✅ {event_flow_path}")

    # 3. Update README counts
    print("📝 Updating README.md component counts...")
    update_readme_counts(manifest)
    print()

    # Validate manual docs
    print("🔍 Checking for manual documentation...")
    missing_docs = validate_manual_docs()

    if missing_docs:
        print()
        print("⚠️  WARNING: Some manual documentation files are missing:")
        for doc in missing_docs:
            print(f"   ❌ {doc}")
        print()
        print("💡 These files need to be created manually or regenerated with Phase 2:")
        print("   See: docs/architecture/README.md for guidance")
        print()
    else:
        print("   ✅ All expected manual docs found")
        print()

    # Summary
    print("=" * 70)
    print("✅ Architecture documentation regenerated!")
    print()
    print("📊 Auto-generated files:")
    for file in files_generated:
        print(f"   • {file}")
    print()
    print("📝 Manual files (edit directly):")
    print("   • docs/architecture/event-architecture.md")
    print("   • docs/architecture/realtime-communication.md")
    print("   • docs/architecture/docker-workspace-lifecycle.md")
    print("   • docs/architecture/infrastructure-data-flow.md")
    print("   • docs/architecture/event-flows/workflow-creation.md")
    print()
    print("🏗️  VSA diagram:")
    print("   • Run `just diagram` to regenerate docs/architecture/vsa-overview.svg")
    print()


if __name__ == "__main__":
    main()
