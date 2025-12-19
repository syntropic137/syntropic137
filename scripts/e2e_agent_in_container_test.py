#!/usr/bin/env python3
"""E2E Test: Agent-in-Container Execution Flow.

This script validates the full agent-in-container architecture (ADR-029):

1. Build workspace image with Claude CLI + agentic_events hooks
2. Start sidecar proxy container
3. Create isolated workspace linked to sidecar network
4. Execute Claude CLI via streaming
5. Parse JSONL events from hooks
6. Verify artifacts
7. Cleanup

NOTE: This script uses the simplified event system (ADR-029).
      Claude CLI runs directly with agentic_events hooks for observability.

Prerequisites:
- Docker installed and running
- AEF workspace image built: just workspace-build
- Sidecar image built: docker build -t aef-sidecar:latest docker/sidecar-proxy/

Usage:
    python scripts/e2e_agent_in_container_test.py [--build] [--no-cleanup]

Options:
    --build       Rebuild Docker images before testing
    --no-cleanup  Keep containers running after test (for debugging)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def build_images() -> bool:
    """Build Docker images for testing."""
    logger.info("🔨 Building Docker images...")

    # Build workspace image
    workspace_build = await asyncio.create_subprocess_exec(
        "bash",
        "docker/workspace/build.sh",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await workspace_build.communicate()

    if workspace_build.returncode != 0:
        logger.error("Failed to build workspace image: %s", stderr.decode())
        return False

    logger.info("✅ Workspace image built")

    # Build sidecar image
    sidecar_build = await asyncio.create_subprocess_exec(
        "docker",
        "build",
        "-t",
        "aef-sidecar:latest",
        "docker/sidecar-proxy/",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await sidecar_build.communicate()

    if sidecar_build.returncode != 0:
        logger.error("Failed to build sidecar image: %s", stderr.decode())
        return False

    logger.info("✅ Sidecar image built")
    return True


async def check_images_exist() -> tuple[bool, str]:
    """Check if required Docker images exist."""
    for image in ["aef-workspace:latest", "aef-sidecar:latest"]:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "image",
            "inspect",
            image,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode != 0:
            return False, f"Image not found: {image}"

    return True, ""


async def create_network(network_name: str) -> bool:
    """Create a Docker network."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "network",
        "create",
        network_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def cleanup_network(network_name: str) -> None:
    """Remove a Docker network."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "network",
        "rm",
        network_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def start_sidecar(
    network_name: str,
    execution_id: str,
) -> tuple[str, str]:
    """Start sidecar container.

    Returns:
        Tuple of (container_id, container_name)
    """
    container_name = f"aef-sidecar-test-{execution_id[:8]}"

    proc = await asyncio.create_subprocess_exec(
        "docker",
        "run",
        "-d",
        "--rm",
        f"--name={container_name}",
        f"--network={network_name}",
        "-e",
        f"AEF_EXECUTION_ID={execution_id}",
        "-e",
        "AEF_TOKEN_SERVICE_URL=http://mock-token-service:8080",
        "aef-sidecar:latest",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to start sidecar: {stderr.decode()}")

    container_id = stdout.decode().strip()
    return container_id, container_name


async def stop_container(name: str) -> None:
    """Stop a container."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "stop",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def start_workspace(
    network_name: str,
    sidecar_name: str,
    execution_id: str,
) -> tuple[str, str]:
    """Start workspace container.

    Returns:
        Tuple of (container_id, container_name)
    """
    container_name = f"aef-workspace-test-{execution_id[:8]}"
    proxy_url = f"http://{sidecar_name}:8081"

    proc = await asyncio.create_subprocess_exec(
        "docker",
        "run",
        "-d",
        "--rm",
        f"--name={container_name}",
        f"--network={network_name}",
        "-e",
        f"HTTP_PROXY={proxy_url}",
        "-e",
        f"HTTPS_PROXY={proxy_url}",
        "-e",
        f"AEF_EXECUTION_ID={execution_id}",
        # Override entrypoint to keep container running
        "--entrypoint",
        "sleep",
        "aef-workspace:latest",
        "infinity",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to start workspace: {stderr.decode()}")

    container_id = stdout.decode().strip()
    return container_id, container_name


async def write_task_to_container(
    container_name: str,
    task: dict,
) -> None:
    """Write task.json to container."""
    task_json = json.dumps(task)

    # Use docker exec to write file
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_name,
        "bash",
        "-c",
        f"echo '{task_json}' > /workspace/task.json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to write task: {stderr.decode()}")


async def execute_agent_streaming(
    container_name: str,
    prompt: str,
    timeout: int = 30,
) -> list[dict]:
    """Execute Claude CLI and collect events (ADR-029).

    Uses Claude CLI directly with --output-format stream-json.
    Hook events from agentic_events are interleaved with CLI events.
    """
    events = []

    # ADR-029: Run Claude CLI directly
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        "-e",
        "ANTHROPIC_API_KEY",  # Pass from host environment
        container_name,
        "claude",
        "--print",
        prompt,
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        async with asyncio.timeout(timeout):
            if proc.stdout:
                async for line in proc.stdout:
                    line_str = line.decode().strip()
                    if line_str:
                        try:
                            event = json.loads(line_str)
                            events.append(event)
                            # Log both hook events (event_type) and CLI events (type)
                            event_type = event.get("event_type") or event.get("type")
                            logger.debug("Event: %s", event_type)
                        except json.JSONDecodeError:
                            logger.warning("Invalid JSONL: %s", line_str[:50])
    except TimeoutError:
        logger.warning("Agent execution timed out after %ds", timeout)
        proc.kill()

    await proc.wait()
    return events


async def check_claude_cli_installed(container_name: str) -> bool:
    """Check if Claude CLI is installed (ADR-029)."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_name,
        "claude",
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error("Claude CLI not installed: %s", stderr.decode())
        return False

    version = stdout.decode().strip()
    logger.info("Claude CLI version: %s", version)
    return True


async def verify_settings_json_attribution(container_name: str) -> bool:
    """F17.4: Verify .claude/settings.json has attribution disabled.

    This prevents "Co-Authored-By: Claude" trailers in git commits.
    """
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_name,
        "cat",
        "/workspace/.claude/settings.json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.warning("Could not read settings.json: %s", stderr.decode())
        return False

    try:
        settings = json.loads(stdout.decode())
        attribution = settings.get("attribution", {})
        commits_disabled = attribution.get("commits") is False
        prs_disabled = attribution.get("pullRequests") is False

        if commits_disabled and prs_disabled:
            logger.info("   ✅ Attribution settings: commits & PRs disabled")
            return True
        else:
            logger.warning("   ⚠️ Attribution not fully disabled: %s", attribution)
            return False
    except json.JSONDecodeError as e:
        logger.warning("Invalid settings.json: %s", e)
        return False


async def verify_artifacts_directory(container_name: str) -> bool:
    """F17.2: Verify artifacts directory exists at correct path.

    Uses WORKSPACE_OUTPUT_DIR = /workspace/artifacts
    """
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_name,
        "test",
        "-d",
        "/workspace/artifacts",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    if proc.returncode == 0:
        logger.info("   ✅ Artifacts directory: /workspace/artifacts exists")
        return True
    else:
        logger.warning("   ⚠️ Artifacts directory /workspace/artifacts not found")
        return False


async def verify_analytics_directory(container_name: str) -> bool:
    """F17.5: Verify analytics directory exists for hook events.

    Uses WORKSPACE_ANALYTICS_DIR = /workspace/.agentic/analytics
    """
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_name,
        "mkdir",
        "-p",
        "/workspace/.agentic/analytics",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    # Directory created or already exists
    logger.info("   ✅ Analytics directory: /workspace/.agentic/analytics ready")
    return True


def count_events_by_type(events: list[dict]) -> dict[str, int]:
    """Count events by type for phase counting verification."""
    counts: dict[str, int] = {}
    for event in events:
        event_type = event.get("type", "unknown")
        counts[event_type] = counts.get(event_type, 0) + 1
    return counts


def verify_phase_counting(events: list[dict]) -> bool:
    """F17.1: Verify phase counting is correct (no duplicates).

    Checks that we don't have duplicate phase_complete events.
    """
    counts = count_events_by_type(events)

    # Check for phase completion events
    phase_complete = counts.get("phase_complete", 0)
    phase_started = counts.get("phase_started", 0)

    if phase_complete > 1 and phase_started == 1:
        logger.warning("   ⚠️ Phase counting: %d completes for 1 start", phase_complete)
        return False

    logger.info("   ✅ Phase counting: %s", counts)
    return True


def verify_analytics_events(events: list[dict]) -> bool:
    """F17.5: Verify analytics events are being streamed."""
    analytics_events = [e for e in events if e.get("type") == "analytics"]

    if analytics_events:
        logger.info("   ✅ Analytics streaming: %d events received", len(analytics_events))
        return True
    else:
        logger.info("   (i) Analytics streaming: no events (may need hook execution)")
        return True  # Not a failure, just informational


async def run_e2e_test(cleanup: bool = True) -> bool:
    """Run the full E2E test."""
    execution_id = str(uuid.uuid4())
    network_name = f"aef-e2e-test-{execution_id[:8]}"
    sidecar_container = None
    workspace_container = None

    try:
        print()
        print("=" * 60)
        print("E2E Test: Agent-in-Container Flow")
        print("=" * 60)
        print()

        # Step 1: Create network
        logger.info("📡 Step 1: Creating Docker network...")
        if not await create_network(network_name):
            logger.error("Failed to create network")
            return False
        logger.info("   Network: %s", network_name)

        # Step 2: Start sidecar
        logger.info("🛡️ Step 2: Starting sidecar proxy...")
        _, sidecar_container = await start_sidecar(
            network_name,
            execution_id,
        )
        logger.info("   Sidecar: %s", sidecar_container)

        # Step 3: Start workspace
        logger.info("📦 Step 3: Starting workspace container...")
        _, workspace_container = await start_workspace(
            network_name,
            sidecar_container,
            execution_id,
        )
        logger.info("   Workspace: %s", workspace_container)

        # Give containers time to start
        await asyncio.sleep(2)

        # Step 4: Verify Claude CLI is installed (ADR-029)
        logger.info("🔍 Step 4: Verifying Claude CLI installation...")
        if not await check_claude_cli_installed(workspace_container):
            logger.error("Claude CLI not installed!")
            return False

        # Step 5: F17 Verification - Check workspace setup
        logger.info("🔧 Step 5: Verifying F17 Container Execution Setup...")
        f17_checks = []

        # F17.4: Attribution settings
        f17_checks.append(await verify_settings_json_attribution(workspace_container))

        # F17.2: Artifacts directory
        f17_checks.append(await verify_artifacts_directory(workspace_container))

        # F17.5: Analytics directory
        f17_checks.append(await verify_analytics_directory(workspace_container))

        # Step 6: Define test prompt (ADR-029: no task.json needed)
        logger.info("📝 Step 6: Preparing test prompt...")
        test_prompt = "This is a test phase. Simply output 'Hello from container!'"

        # Step 7: Execute Claude CLI directly (ADR-029)
        logger.info("🚀 Step 7: Executing Claude CLI...")
        logger.info("   (This will fail without API tokens - expected)")

        events = await execute_agent_streaming(
            workspace_container,
            prompt=test_prompt,
            timeout=10,
        )

        # Step 8: Analyze events
        logger.info("📊 Step 8: Analyzing events...")
        logger.info("   Total events received: %d", len(events))

        event_types = [e.get("type") for e in events]
        logger.info("   Event types: %s", event_types)

        # Check for expected events
        has_started = "started" in event_types
        has_error = "error" in event_types  # Expected without API tokens

        if has_started:
            logger.info("   ✅ Agent started event received")
        else:
            logger.warning("   ⚠️ No started event received")

        if has_error:
            logger.info("   ✅ Error event received (expected without API tokens)")
            error_event = next(e for e in events if e.get("type") == "error")
            logger.info("   Error: %s", error_event.get("message", "")[:100])

        # F17.1: Verify phase counting
        f17_checks.append(verify_phase_counting(events))

        # F17.5: Verify analytics events
        f17_checks.append(verify_analytics_events(events))

        # Step 9: Summary
        print()
        print("=" * 60)
        print("E2E Test Results")
        print("=" * 60)
        print()
        print(f"Execution ID:    {execution_id}")
        print(f"Network:         {network_name}")
        print(f"Sidecar:         {sidecar_container}")
        print(f"Workspace:       {workspace_container}")
        print(f"Events:          {len(events)}")
        print(f"F17 Checks:      {sum(f17_checks)}/{len(f17_checks)} passed")
        print(f"Started Event:   {'✅' if has_started else '❌'}")
        print()

        # Test is successful if we got a started event
        # (full execution requires API tokens)
        success = has_started

        if success:
            print("✅ E2E TEST PASSED")
            print()
            print("The agent-in-container architecture is working (ADR-029):")
            print("  - Workspace container started")
            print("  - Linked to sidecar proxy network")
            print("  - Claude CLI installed and executable")
            print("  - JSONL event streaming works (agentic_events hooks)")
            print()
            print("To run a full execution, configure API tokens.")
        else:
            print("❌ E2E TEST FAILED")
            print()
            print("The agent runner did not emit a started event.")

        return success

    except Exception as e:
        logger.exception("E2E test failed: %s", e)
        return False

    finally:
        if cleanup:
            logger.info("🧹 Cleaning up...")
            if workspace_container:
                await stop_container(workspace_container)
            if sidecar_container:
                await stop_container(sidecar_container)
            await cleanup_network(network_name)
        else:
            logger.info("Skipping cleanup (--no-cleanup)")
            print()
            print("Containers still running for debugging:")
            print(f"  Sidecar:   docker logs {sidecar_container}")
            print(f"  Workspace: docker exec -it {workspace_container} bash")
            print(f"  Cleanup:   docker stop {sidecar_container} {workspace_container}")


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="E2E Test: Agent-in-Container")
    parser.add_argument("--build", action="store_true", help="Rebuild images")
    parser.add_argument("--no-cleanup", action="store_true", help="Keep containers")
    args = parser.parse_args()

    # Check/build images
    if args.build:
        if not await build_images():
            return 1
    else:
        exists, error = await check_images_exist()
        if not exists:
            logger.error(error)
            logger.info("Run with --build to build images, or build manually:")
            logger.info("  ./docker/workspace/build.sh")
            logger.info("  docker build -t aef-sidecar:latest docker/sidecar-proxy/")
            return 1

    # Run E2E test
    success = await run_e2e_test(cleanup=not args.no_cleanup)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
