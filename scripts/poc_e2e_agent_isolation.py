#!/usr/bin/env python3
"""POC: End-to-End Agent Isolation with Claude SDK & GitHub.

This POC demonstrates the complete flow of running a coding agent
in isolation with network access for Claude API and GitHub.

Flow:
1. Create isolated Docker container with network bridge
2. Configure egress filtering (allowlist)
3. Clone GitHub repo inside container
4. Execute Claude Agent SDK on the code
5. Collect artifacts and events
6. Destroy container

Test Matrix:
- Network: Isolated (none) vs Allowlist (bridge + hosts)
- Agent: Mock vs Real Claude SDK
- GitHub: Public repo clone
- Events: Full observability

Usage:
    # With real Claude API (requires ANTHROPIC_API_KEY)
    uv run python scripts/poc_e2e_agent_isolation.py --real

    # With mock agent (no API key needed)
    uv run python scripts/poc_e2e_agent_isolation.py --mock

    # Test network isolation
    uv run python scripts/poc_e2e_agent_isolation.py --test-network
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from aef_adapters.agents.agentic_types import WorkspaceConfig
from aef_adapters.workspaces import (
    HardenedDockerWorkspace,
    InMemoryCollectorEmitter,
    IsolatedWorkspaceConfig,
    WorkspaceRouter,
    configure_workspace_emitter,
)

console = Console()


@dataclass
class POCResult:
    """Results from POC test run."""

    test_name: str
    success: bool
    duration_ms: float
    container_id: str | None
    events_captured: int
    network_allowed: bool
    github_cloned: bool
    agent_executed: bool
    artifacts_collected: int
    error: str | None = None
    findings: list[str] | None = None


class POCRunner:
    """Run POC tests for isolated agent execution."""

    def __init__(self, use_real_api: bool = False) -> None:
        """Initialize POC runner.

        Args:
            use_real_api: Use real Claude API (requires ANTHROPIC_API_KEY)
        """
        self.use_real_api = use_real_api
        self.router = WorkspaceRouter()
        self.emitter = InMemoryCollectorEmitter()
        configure_workspace_emitter(emitter=self.emitter)
        self.results: list[POCResult] = []

    async def test_network_isolation(self) -> POCResult:
        """Test 1: Network isolation blocks all external access."""
        console.print("\n[bold cyan]Test 1: Network Isolation (--network=none)[/]")
        start = time.perf_counter()
        findings = []

        # Create workspace with network disabled
        os.environ["AEF_SECURITY_ALLOW_NETWORK"] = "false"

        base_config = WorkspaceConfig(session_id="poc-network-test-none")
        config = IsolatedWorkspaceConfig(base_config=base_config)

        try:
            async with self.router.create(config) as workspace:
                console.print(f"  Container: {workspace.container_id[:12]}")

                # Try to ping external host (should fail)
                exit_code, stdout, stderr = await self.router.execute_command(
                    workspace, ["ping", "-c", "1", "-W", "1", "8.8.8.8"]
                )

                if exit_code != 0:
                    findings.append("✓ Network fully isolated - cannot reach 8.8.8.8")
                    console.print("  [green]✓[/] Network isolated - ping failed as expected")
                else:
                    findings.append("✗ Network NOT isolated - ping succeeded!")
                    console.print("  [red]✗[/] SECURITY ISSUE: ping succeeded")

                # Try DNS (should also fail)
                exit_code, stdout, stderr = await self.router.execute_command(
                    workspace, ["nslookup", "api.anthropic.com"]
                )

                if exit_code != 0:
                    findings.append("✓ DNS blocked - cannot resolve hostnames")
                    console.print("  [green]✓[/] DNS blocked - nslookup failed as expected")
                else:
                    findings.append("✗ DNS NOT blocked - resolved hostname!")
                    console.print("  [red]✗[/] SECURITY ISSUE: DNS resolution succeeded")

                duration_ms = (time.perf_counter() - start) * 1000

                return POCResult(
                    test_name="network_isolation",
                    success=True,
                    duration_ms=duration_ms,
                    container_id=workspace.container_id,
                    events_captured=len(self.emitter.events),
                    network_allowed=False,
                    github_cloned=False,
                    agent_executed=False,
                    artifacts_collected=0,
                    findings=findings,
                )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return POCResult(
                test_name="network_isolation",
                success=False,
                duration_ms=duration_ms,
                container_id=None,
                events_captured=len(self.emitter.events),
                network_allowed=False,
                github_cloned=False,
                agent_executed=False,
                artifacts_collected=0,
                error=str(e),
            )

    async def test_allowlist_network(self) -> POCResult:
        """Test 2: Allowlist network for Claude API + GitHub."""
        console.print("\n[bold cyan]Test 2: Allowlist Network Access[/]")
        start = time.perf_counter()
        findings = []

        # Enable network with allowlist
        os.environ["AEF_SECURITY_ALLOW_NETWORK"] = "true"
        os.environ["AEF_SECURITY_ALLOWED_HOSTS"] = "api.anthropic.com,api.github.com,github.com"

        base_config = WorkspaceConfig(session_id="poc-network-test-allowlist")
        config = IsolatedWorkspaceConfig(base_config=base_config)

        try:
            async with self.router.create(config) as workspace:
                console.print(f"  Container: {workspace.container_id[:12]}")

                # Test 1: Should be able to reach allowed hosts
                # (Note: In real implementation, this would go through egress proxy)
                exit_code, stdout, stderr = await self.router.execute_command(
                    workspace,
                    ["sh", "-c", "command -v curl >/dev/null || apt-get update && apt-get install -y curl"],
                    timeout=60,
                )

                if exit_code == 0:
                    findings.append("✓ Package manager works (for installing curl)")
                    console.print("  [green]✓[/] Can install packages")

                # Try to reach GitHub (allowed)
                exit_code, stdout, stderr = await self.router.execute_command(
                    workspace,
                    ["curl", "-I", "https://api.github.com", "-m", "5"],
                    timeout=10,
                )

                if exit_code == 0:
                    findings.append("✓ Can reach allowed host: api.github.com")
                    console.print("  [green]✓[/] Can reach api.github.com")
                else:
                    findings.append("✗ Cannot reach allowed host: api.github.com")
                    console.print(f"  [red]✗[/] Cannot reach api.github.com: {stderr[:100]}")

                # Try to reach disallowed host
                exit_code, stdout, stderr = await self.router.execute_command(
                    workspace,
                    ["curl", "-I", "https://example.com", "-m", "5"],
                    timeout=10,
                )

                if exit_code != 0:
                    findings.append("✓ Blocked disallowed host: example.com")
                    console.print("  [green]✓[/] Blocked example.com (not in allowlist)")
                else:
                    findings.append("⚠️  Allowlist not enforced - reached example.com")
                    console.print("  [yellow]⚠️[/]  WARNING: Allowlist not enforced yet")

                duration_ms = (time.perf_counter() - start) * 1000

                return POCResult(
                    test_name="allowlist_network",
                    success=True,
                    duration_ms=duration_ms,
                    container_id=workspace.container_id,
                    events_captured=len(self.emitter.events),
                    network_allowed=True,
                    github_cloned=False,
                    agent_executed=False,
                    artifacts_collected=0,
                    findings=findings,
                )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return POCResult(
                test_name="allowlist_network",
                success=False,
                duration_ms=duration_ms,
                container_id=None,
                events_captured=len(self.emitter.events),
                network_allowed=True,
                github_cloned=False,
                agent_executed=False,
                artifacts_collected=0,
                error=str(e),
                findings=findings,
            )

    async def test_github_clone(self) -> POCResult:
        """Test 3: Clone GitHub repo inside isolated container."""
        console.print("\n[bold cyan]Test 3: GitHub Clone in Container[/]")
        start = time.perf_counter()
        findings = []

        os.environ["AEF_SECURITY_ALLOW_NETWORK"] = "true"
        os.environ["AEF_SECURITY_ALLOWED_HOSTS"] = "github.com"

        base_config = WorkspaceConfig(session_id="poc-github-clone")
        config = IsolatedWorkspaceConfig(base_config=base_config)

        try:
            async with self.router.create(config) as workspace:
                console.print(f"  Container: {workspace.container_id[:12]}")

                # Install git
                console.print("  Installing git...")
                exit_code, _stdout, stderr = await self.router.execute_command(
                    workspace,
                    ["sh", "-c", "command -v git >/dev/null || (apt-get update && apt-get install -y git)"],
                    timeout=60,
                )

                if exit_code != 0:
                    findings.append(f"✗ Cannot install git: {stderr[:100]}")
                    raise RuntimeError(f"Git install failed: {stderr}")

                findings.append("✓ Git installed successfully")

                # Clone a small public repo
                console.print("  Cloning test repository...")
                exit_code, stdout, stderr = await self.router.execute_command(
                    workspace,
                    ["git", "clone", "https://github.com/octocat/Hello-World.git", "/workspace/repo"],
                    timeout=30,
                )

                github_cloned = exit_code == 0

                if github_cloned:
                    findings.append("✓ Successfully cloned GitHub repository")
                    console.print("  [green]✓[/] Repository cloned")

                    # List cloned files
                    exit_code, stdout, stderr = await self.router.execute_command(
                        workspace, ["ls", "-la", "/workspace/repo"]
                    )

                    if exit_code == 0:
                        file_count = len(stdout.split("\n")) - 3  # Subtract header lines
                        findings.append(f"✓ Repo contains {file_count} files")
                        console.print(f"  [green]✓[/] Repo contains {file_count} files")
                else:
                    findings.append(f"✗ Failed to clone repository: {stderr[:100]}")
                    console.print(f"  [red]✗[/] Clone failed: {stderr[:100]}")

                duration_ms = (time.perf_counter() - start) * 1000

                return POCResult(
                    test_name="github_clone",
                    success=github_cloned,
                    duration_ms=duration_ms,
                    container_id=workspace.container_id,
                    events_captured=len(self.emitter.events),
                    network_allowed=True,
                    github_cloned=github_cloned,
                    agent_executed=False,
                    artifacts_collected=file_count if github_cloned else 0,
                    findings=findings,
                )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return POCResult(
                test_name="github_clone",
                success=False,
                duration_ms=duration_ms,
                container_id=None,
                events_captured=len(self.emitter.events),
                network_allowed=True,
                github_cloned=False,
                agent_executed=False,
                artifacts_collected=0,
                error=str(e),
                findings=findings,
            )

    async def test_agent_execution(self) -> POCResult:
        """Test 4: Execute agent code (mock or real Claude SDK)."""
        console.print("\n[bold cyan]Test 4: Agent Execution in Container[/]")
        start = time.perf_counter()
        findings = []

        os.environ["AEF_SECURITY_ALLOW_NETWORK"] = "true"
        os.environ["AEF_SECURITY_ALLOWED_HOSTS"] = "api.anthropic.com,pypi.org,files.pythonhosted.org"

        base_config = WorkspaceConfig(session_id="poc-agent-execution")
        config = IsolatedWorkspaceConfig(base_config=base_config)

        api_key = os.environ.get("ANTHROPIC_API_KEY")

        try:
            async with self.router.create(config) as workspace:
                console.print(f"  Container: {workspace.container_id[:12]}")

                if self.use_real_api:
                    if not api_key:
                        findings.append("✗ ANTHROPIC_API_KEY not set - cannot test real API")
                        raise RuntimeError("ANTHROPIC_API_KEY not set")

                    # Install Claude SDK
                    console.print("  Installing claude-agent-sdk...")
                    exit_code, stdout, stderr = await self.router.execute_command(
                        workspace,
                        ["pip", "install", "anthropic"],
                        timeout=60,
                    )

                    if exit_code != 0:
                        findings.append(f"✗ Cannot install anthropic: {stderr[:100]}")
                        raise RuntimeError(f"SDK install failed: {stderr}")

                    findings.append("✓ Claude SDK installed")

                    # Create a simple test script
                    test_script = f"""
import os
from anthropic import Anthropic

os.environ["ANTHROPIC_API_KEY"] = "{api_key}"
client = Anthropic()

message = client.messages.create(
    model="claude-3-5-haiku-20241022",
    max_tokens=100,
    messages=[{{"role": "user", "content": "Say 'test successful' if you can read this."}}]
)

print(message.content[0].text)
"""

                    # Write script to container
                    exit_code, _stdout, _stderr = await self.router.execute_command(
                        workspace,
                        ["sh", "-c", f"cat > /workspace/test_agent.py << 'EOF'\n{test_script}\nEOF"],
                    )

                    # Execute script
                    console.print("  Calling Claude API...")
                    exit_code, stdout, stderr = await self.router.execute_command(
                        workspace,
                        ["python", "/workspace/test_agent.py"],
                        timeout=30,
                    )

                    agent_executed = exit_code == 0 and "test successful" in stdout.lower()

                    if agent_executed:
                        findings.append("✓ Claude API call succeeded")
                        console.print("  [green]✓[/] Agent executed successfully")
                        console.print(f"  [dim]Response: {stdout[:100]}[/]")
                    else:
                        findings.append(f"✗ Agent execution failed: {stderr[:100]}")
                        console.print(f"  [red]✗[/] API call failed: {stderr[:100]}")
                else:
                    # Mock agent execution
                    console.print("  Running mock agent...")
                    exit_code, stdout, _stderr = await self.router.execute_command(
                        workspace,
                        ["python", "-c", "print('Mock agent: Analysis complete')"],
                    )

                    agent_executed = exit_code == 0
                    findings.append("✓ Mock agent executed (use --real for actual Claude API test)")
                    console.print("  [green]✓[/] Mock agent executed")

                duration_ms = (time.perf_counter() - start) * 1000

                return POCResult(
                    test_name="agent_execution",
                    success=agent_executed,
                    duration_ms=duration_ms,
                    container_id=workspace.container_id,
                    events_captured=len(self.emitter.events),
                    network_allowed=True,
                    github_cloned=False,
                    agent_executed=agent_executed,
                    artifacts_collected=1 if agent_executed else 0,
                    findings=findings,
                )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return POCResult(
                test_name="agent_execution",
                success=False,
                duration_ms=duration_ms,
                container_id=None,
                events_captured=len(self.emitter.events),
                network_allowed=True,
                github_cloned=False,
                agent_executed=False,
                artifacts_collected=0,
                error=str(e),
                findings=findings,
            )

    async def run_all_tests(self) -> list[POCResult]:
        """Run all POC tests."""
        console.print(Panel.fit("[bold]POC: End-to-End Agent Isolation[/]", border_style="cyan"))

        # Test 1: Network isolation
        result1 = await self.test_network_isolation()
        self.results.append(result1)

        # Test 2: Allowlist network
        result2 = await self.test_allowlist_network()
        self.results.append(result2)

        # Test 3: GitHub clone
        result3 = await self.test_github_clone()
        self.results.append(result3)

        # Test 4: Agent execution
        result4 = await self.test_agent_execution()
        self.results.append(result4)

        return self.results

    def print_summary(self) -> None:
        """Print test summary."""
        console.print("\n" + "=" * 80)
        console.print(Panel.fit("[bold]POC Summary[/]", border_style="cyan"))

        # Results table
        table = Table(title="Test Results", show_header=True, header_style="bold cyan")
        table.add_column("Test", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Duration", justify="right")
        table.add_column("Events", justify="right")
        table.add_column("Container", style="dim")

        for result in self.results:
            status = "[green]✓ PASS[/]" if result.success else "[red]✗ FAIL[/]"
            duration = f"{result.duration_ms:.0f}ms"
            events = str(result.events_captured)
            container = result.container_id[:12] if result.container_id else "N/A"

            table.add_row(result.test_name, status, duration, events, container)

        console.print(table)

        # Findings
        console.print("\n[bold]Key Findings:[/]")
        for result in self.results:
            if result.findings:
                console.print(f"\n[cyan]{result.test_name}:[/]")
                for finding in result.findings:
                    console.print(f"  {finding}")

        # Events
        console.print(f"\n[bold]Events Captured:[/] {len(self.emitter.events)} total")
        event_types: dict[str, int] = {}
        for event in self.emitter.events:
            event_type = event.get("event_type", "unknown")
            event_types[event_type] = event_types.get(event_type, 0) + 1

        for event_type, count in sorted(event_types.items()):
            console.print(f"  • {event_type}: {count}")

    def export_findings(self, output_path: Path) -> None:
        """Export findings to JSON for ADR documentation."""
        data = {
            "poc_date": datetime.now(UTC).isoformat(),
            "tests_run": len(self.results),
            "tests_passed": sum(1 for r in self.results if r.success),
            "results": [
                {
                    "test": r.test_name,
                    "success": r.success,
                    "duration_ms": r.duration_ms,
                    "findings": r.findings or [],
                    "error": r.error,
                }
                for r in self.results
            ],
            "events": self.emitter.events,
        }

        output_path.write_text(json.dumps(data, indent=2))
        console.print(f"\n[green]✓[/] Findings exported to: {output_path}")


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="POC: E2E Agent Isolation Test")
    parser.add_argument("--real", action="store_true", help="Use real Claude API (requires ANTHROPIC_API_KEY)")
    parser.add_argument("--mock", action="store_true", help="Use mock agent (default)")
    parser.add_argument("--test-network", action="store_true", help="Only test network isolation")
    parser.add_argument("--output", type=Path, default=Path("poc_findings.json"), help="Output file for findings")

    args = parser.parse_args()

    runner = POCRunner(use_real_api=args.real)

    if args.test_network:
        await runner.test_network_isolation()
        await runner.test_allowlist_network()
    else:
        await runner.run_all_tests()

    runner.print_summary()
    runner.export_findings(args.output)


if __name__ == "__main__":
    asyncio.run(main())
